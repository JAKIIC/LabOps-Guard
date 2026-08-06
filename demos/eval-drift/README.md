# LABOPS-AT-004 evaluation preprocessing drift fixture

The fixed checkpoint, validation data and metric produce about 97.81% accuracy
with `eval_standard`. The incident configuration mistakenly enables the
deterministic `train_augmented` profile and produces about 71.88%.

`build_fixture.py` creates the checkpoint and validation tensor inside an
offline PyTorch container. `evaluate.py` computes both metrics from those
artifacts; neither value is embedded in the evaluator or Runner.

