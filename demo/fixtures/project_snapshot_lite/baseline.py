#!/usr/bin/env python3
"""Sample-calibrated ordered-statistics decoder for POLAR(64, 32)."""

from __future__ import annotations

import argparse
import io
from itertools import combinations
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
BIT_COLUMNS = [f"bit_{index}" for index in range(64)]
Y_COLUMNS = [f"y_{index}" for index in range(64)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-dir", type=Path, default=ROOT / "train")
    parser.add_argument("--calibration-rows", type=int, default=10000)
    parser.add_argument("--validation-rows", type=int, default=2000)
    parser.add_argument("--calibration", type=Path, default=ROOT / "channel_calibration.npz")
    parser.add_argument("--reuse-calibration", action="store_true")
    parser.add_argument("--test-zip", type=Path, default=ROOT / "public_test.zip")
    parser.add_argument("--test-csv", type=Path, default=None)
    parser.add_argument("--matrix", type=Path, default=None)
    parser.add_argument("--baseline-zip", type=Path, default=ROOT / "baseline.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "submission.csv")
    parser.add_argument("--list-size", type=int, default=10)
    parser.add_argument("--order", type=int, choices=(0, 1, 2, 3), default=2)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--max-rows", type=int, default=None, help="Debug inference only.")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_parity_matrix(args: argparse.Namespace) -> np.ndarray:
    if args.matrix is not None:
        matrix = np.loadtxt(args.matrix, dtype=np.uint8)
    else:
        with ZipFile(args.baseline_zip) as archive:
            raw = archive.read("baseline/Codes_DB/POLAR_N64_K32.txt")
        matrix = np.loadtxt(io.BytesIO(raw), dtype=np.uint8)
    if matrix.shape != (32, 64):
        raise ValueError(f"Expected a 32x64 parity-check matrix, got {matrix.shape}")
    return matrix


def rref_binary(matrix: np.ndarray) -> tuple[np.ndarray, list[int]]:
    reduced = matrix.copy().astype(np.uint8)
    pivots: list[int] = []
    row = 0
    for column in range(reduced.shape[1]):
        candidates = np.flatnonzero(reduced[row:, column])
        if candidates.size == 0:
            continue
        selected = row + int(candidates[0])
        reduced[[row, selected]] = reduced[[selected, row]]
        other_rows = np.flatnonzero(reduced[:, column])
        other_rows = other_rows[other_rows != row]
        reduced[other_rows] ^= reduced[row]
        pivots.append(column)
        row += 1
        if row == reduced.shape[0]:
            break
    return reduced, pivots


def generator_from_parity(parity: np.ndarray) -> np.ndarray:
    reduced, pivots = rref_binary(parity)
    free = np.asarray([index for index in range(64) if index not in pivots], dtype=int)
    generator = np.zeros((len(free), 64), dtype=np.uint8)
    generator[np.arange(len(free)), free] = 1
    generator[:, np.asarray(pivots)] = reduced[:, free].T
    if np.any((generator @ parity.T) % 2):
        raise RuntimeError("Generator matrix does not satisfy the parity checks")
    return generator


def discover_training_pair(train_dir: Path) -> tuple[Path, Path]:
    for x_path in sorted(train_dir.glob("train_codeword_x_shard_*.csv")):
        suffix = x_path.stem.rsplit("_", 1)[-1]
        y_path = train_dir / f"train_noisy_y_shard_{suffix}.csv"
        if y_path.exists():
            return x_path, y_path
    raise FileNotFoundError(
        f"No paired training shard found in {train_dir}. See README.md for download paths."
    )


def load_training_sample(
    train_dir: Path, total_rows: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    x_path, y_path = discover_training_pair(train_dir)
    x_frame = pd.read_csv(x_path, usecols=["id", *BIT_COLUMNS], nrows=total_rows)
    y_frame = pd.read_csv(y_path, usecols=["id", *Y_COLUMNS], nrows=total_rows)
    if len(x_frame) < total_rows:
        raise ValueError(f"Requested {total_rows} rows, but {x_path.name} has only {len(x_frame)}")
    if not np.array_equal(x_frame["id"].to_numpy(), y_frame["id"].to_numpy()):
        raise ValueError(f"IDs are not aligned: {x_path.name}, {y_path.name}")
    codewords = x_frame[BIT_COLUMNS].to_numpy(dtype=np.uint8)
    received = y_frame[Y_COLUMNS].to_numpy(dtype=np.float32)
    permutation = np.random.default_rng(seed).permutation(total_rows)
    print(f"Sampled {total_rows} rows from shard {x_path.stem.rsplit('_', 1)[-1]}")
    return received[permutation], codewords[permutation]


def fit_channel(received: np.ndarray, codewords: np.ndarray) -> dict[str, np.ndarray]:
    mean_zero = np.zeros(64, dtype=np.float32)
    mean_one = np.zeros(64, dtype=np.float32)
    variance = np.zeros(64, dtype=np.float32)
    prior_one = (codewords.sum(axis=0) + 1.0) / (len(codewords) + 2.0)
    for bit in range(64):
        zero = codewords[:, bit] == 0
        one = ~zero
        mean_zero[bit] = received[zero, bit].mean() if np.any(zero) else 1.0
        mean_one[bit] = received[one, bit].mean() if np.any(one) else -1.0
        class_means = np.where(zero, mean_zero[bit], mean_one[bit])
        variance[bit] = max(float(np.mean((received[:, bit] - class_means) ** 2)), 1e-2)
    return {
        "mean_zero": mean_zero,
        "mean_one": mean_one,
        "variance": variance,
        "prior_one": prior_one.astype(np.float32),
    }


def calibrated_llr(received: np.ndarray, calibration: dict[str, np.ndarray]) -> np.ndarray:
    mean_zero = calibration["mean_zero"]
    mean_one = calibration["mean_one"]
    variance = calibration["variance"]
    prior_one = calibration["prior_one"]
    midpoint = (mean_zero + mean_one) / 2.0
    llr = (mean_zero - mean_one) / variance * (received - midpoint)
    llr += np.log((1.0 - prior_one) / prior_one)
    return llr.astype(np.float32)


def make_flip_patterns(list_size: int, order: int) -> list[tuple[int, ...]]:
    patterns: list[tuple[int, ...]] = [()]
    for size in range(1, order + 1):
        patterns.extend(combinations(range(list_size), size))
    return patterns


def osd_decode_one(
    llr: np.ndarray, generator: np.ndarray, patterns: list[tuple[int, ...]], list_size: int
) -> np.ndarray:
    # Put reliable columns first, then row-reduce G to obtain a per-sample
    # most-reliable information basis (MRB).
    column_order = np.argsort(-np.abs(llr))
    systematic = generator[:, column_order].copy()
    pivot_columns: list[int] = []
    pivot_row = 0
    for column in range(64):
        candidates = np.flatnonzero(systematic[pivot_row:, column])
        if candidates.size == 0:
            continue
        selected = pivot_row + int(candidates[0])
        systematic[[pivot_row, selected]] = systematic[[selected, pivot_row]]
        other_rows = np.flatnonzero(systematic[:, column])
        other_rows = other_rows[other_rows != pivot_row]
        systematic[other_rows] ^= systematic[pivot_row]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == generator.shape[0]:
            break

    hard_permuted = llr[column_order] < 0.0
    pivot_columns_array = np.asarray(pivot_columns)
    message = hard_permuted[pivot_columns_array].astype(np.uint8)
    base_code = (message @ systematic) % 2
    pivot_reliability = np.abs(llr[column_order[pivot_columns_array]])
    least_reliable_rows = np.argsort(pivot_reliability)[:list_size]
    weights = np.abs(llr[column_order])

    best_code = base_code
    best_cost = float(np.sum(weights * (base_code != hard_permuted)))
    for pattern in patterns[1:]:
        candidate = base_code.copy()
        for local_index in pattern:
            candidate ^= systematic[least_reliable_rows[local_index]]
        cost = float(np.sum(weights * (candidate != hard_permuted)))
        if cost < best_cost:
            best_cost = cost
            best_code = candidate
    decoded = np.empty(64, dtype=np.uint8)
    decoded[column_order] = best_code
    return decoded


def osd_decode(
    llrs: np.ndarray, generator: np.ndarray, list_size: int, order: int
) -> np.ndarray:
    patterns = make_flip_patterns(list_size, order)
    return np.stack(
        [osd_decode_one(row, generator, patterns, list_size) for row in llrs], axis=0
    )


def validate_and_select(
    received: np.ndarray,
    truth: np.ndarray,
    generator: np.ndarray,
    calibration: dict[str, np.ndarray],
    list_size: int,
    order: int,
) -> str:
    raw_osd = osd_decode(received, generator, list_size, order)
    learned_osd = osd_decode(calibrated_llr(received, calibration), generator, list_size, order)
    scores = {
        "hard": float(np.mean((received < 0) != truth)),
        "raw": float(np.mean(raw_osd != truth)),
        "calibrated": float(np.mean(learned_osd != truth)),
    }
    print("Validation BER")
    for name, score in scores.items():
        print(f"  {name:10s}: {score:.6f}")
    selected = min(("raw", "calibrated"), key=scores.get)
    print(f"Selected OSD channel mode: {selected}")
    return selected


def save_calibration(path: Path, calibration: dict[str, np.ndarray], mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **calibration, mode=np.asarray(mode))


def load_calibration(path: Path) -> tuple[dict[str, np.ndarray], str]:
    saved = np.load(path)
    calibration = {name: saved[name] for name in ("mean_zero", "mean_one", "variance", "prior_one")}
    return calibration, str(saved["mode"])


def open_test_source(args: argparse.Namespace):
    if args.test_csv is not None:
        return None, args.test_csv
    archive = ZipFile(args.test_zip)
    return archive, archive.open("competition_data/test_noisy_y_public.csv")


def main() -> None:
    args = parse_args()
    if not 1 <= args.list_size <= 32:
        raise ValueError("--list-size must be between 1 and 32")
    parity = load_parity_matrix(args)
    generator = generator_from_parity(parity)

    if args.reuse_calibration:
        calibration, mode = load_calibration(args.calibration)
        print(f"Loaded calibration from {args.calibration}; mode={mode}")
    else:
        total = args.calibration_rows + args.validation_rows
        received, truth = load_training_sample(args.train_dir, total, args.seed)
        train_y, val_y = received[: args.calibration_rows], received[args.calibration_rows :]
        train_x, val_x = truth[: args.calibration_rows], truth[args.calibration_rows :]
        calibration = fit_channel(train_y, train_x)
        mode = validate_and_select(
            val_y, val_x, generator, calibration, args.list_size, args.order
        )
        save_calibration(args.calibration, calibration, mode)
        print(f"Saved calibration to {args.calibration}")

    archive, source = open_test_source(args)
    output_parts = []
    processed = 0
    try:
        for frame in pd.read_csv(source, chunksize=args.chunk_size):
            if args.max_rows is not None:
                remaining = args.max_rows - processed
                if remaining <= 0:
                    break
                frame = frame.iloc[:remaining]
            received = frame[Y_COLUMNS].to_numpy(dtype=np.float32)
            llrs = calibrated_llr(received, calibration) if mode == "calibrated" else received
            decoded = osd_decode(llrs, generator, args.list_size, args.order)
            output = pd.DataFrame(decoded, columns=BIT_COLUMNS)
            output.insert(0, "id", frame["id"].to_numpy())
            output_parts.append(output)
            processed += len(frame)
            if processed % 10000 == 0 or (args.max_rows is not None and processed == args.max_rows):
                print(f"Decoded {processed} rows")
    finally:
        if archive is not None:
            archive.close()
    if not output_parts:
        raise ValueError("No test rows were read")
    submission = pd.concat(output_parts, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(args.output, index=False)
    print(f"Wrote {len(submission)} rows to {args.output}")


if __name__ == "__main__":
    main()
