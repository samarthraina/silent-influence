"""Config -> explicit list of experimental units.

The grid is a full cross-product of declared axes. There is no experiment enumeration and
no named contrasts: a "condition" is a coordinate, never an index into a table.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from . import candidates as cand
from . import conditions, datasets, protocols, rubrics, templates
from .backends import GenParams, ModelSpec
from .records import derive_seed, unit_id


@dataclass(frozen=True)
class UnitSpec:
    dataset: str
    prompt_id: str
    candidate_response_id: str
    judge_model: str
    evaluated_model: str
    prior_context_condition: str
    prior_score_value: Optional[int]
    rubric_variant: str
    output_protocol: str
    history_template: str
    backend: str
    chat_template_kwargs: str      # canonical JSON, see ModelSpec
    replicate: int

    def key(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def uid(self) -> str:
        return unit_id(self.key())


@dataclass
class Plan:
    run_id: str
    units: List[UnitSpec]
    models: Dict[str, ModelSpec]
    gen_params: GenParams
    base_seed: int
    prompts: Dict[tuple, datasets.PromptRow]
    candidates: Dict[tuple, cand.Candidate]
    config: Dict[str, Any]

    def seed_for(self, u: UnitSpec) -> int:
        return derive_seed(self.base_seed, u.uid)


def load_config(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_plan(config: Dict[str, Any], root: Path, run_id: str) -> Plan:
    exp = config["experiment"]
    base_seed = int(exp.get("seed", 42))
    gen = GenParams(**config.get("generation", {}))

    known = set(ModelSpec.__dataclass_fields__) - {"extra"}
    model_specs: Dict[str, ModelSpec] = {}
    for key in exp["judge_models"]:
        raw = dict(config["models"][key])
        raw.setdefault("key", key)
        # Free-text keys (note, panel_slot, ...) are documentation; keep them on the spec
        # so they reach the manifest rather than being silently dropped.
        extra = {k: v for k, v in raw.items() if k not in known}
        model_specs[key] = ModelSpec(**{k: v for k, v in raw.items() if k in known},
                                     extra=extra)

    conds = conditions.resolve_many(exp["prior_context_conditions"])
    rubric_variants = exp.get("rubric_variants", ["grounded"])
    output_protocols = exp.get("output_protocols", ["score_then_justification"])
    history_template = exp.get("history_template", templates.DEFAULT)
    n_replicates = int(exp.get("replicates", 1))

    for r in rubric_variants:
        rubrics.resolve(r)
    for p in output_protocols:
        protocols.resolve(p)
    templates.resolve(history_template)

    all_cands = cand.load_candidates((root / config["candidates"]["path"]).resolve())
    cand_ix = cand.index(all_cands)

    prompts_by_key: Dict[tuple, datasets.PromptRow] = {}
    cands_by_key: Dict[tuple, cand.Candidate] = {}
    units: List[UnitSpec] = []

    for ds_name in exp["datasets"]:
        ds_spec = config["datasets"][ds_name]
        rows = datasets.load_dataset(ds_name, ds_spec, root)
        rows = datasets.sample(rows, exp.get("n_prompts"), base_seed,
                               stratify=ds_spec.get("stratify", True))
        for row in rows:
            prompts_by_key[(ds_name, row.prompt_id)] = row
            picked = cand.select(cand_ix, ds_name, row.prompt_id,
                                 exp.get("evaluated_models"),
                                 exp.get("candidates_per_prompt"))
            if not picked:
                continue
            for c in picked:
                cands_by_key[(ds_name, row.prompt_id, c.candidate_response_id)] = c
                for jm in exp["judge_models"]:
                    if exp.get("exclude_self_judging", True) and jm == c.evaluated_model:
                        continue
                    for pc in conds:
                        for rv in rubric_variants:
                            for op in output_protocols:
                                for rep in range(n_replicates):
                                    units.append(UnitSpec(
                                        dataset=ds_name,
                                        prompt_id=row.prompt_id,
                                        candidate_response_id=c.candidate_response_id,
                                        judge_model=jm,
                                        evaluated_model=c.evaluated_model,
                                        prior_context_condition=pc.name,
                                        prior_score_value=pc.score,
                                        rubric_variant=rv,
                                        output_protocol=op,
                                        history_template=history_template,
                                        backend=model_specs[jm].backend,
                                        chat_template_kwargs=model_specs[jm]
                                            .canonical_chat_template_kwargs(),
                                        replicate=rep,
                                    ))

    seen = set()
    for u in units:
        if u.uid in seen:
            raise RuntimeError(f"duplicate unit in plan: {u}")
        seen.add(u.uid)

    return Plan(run_id=run_id, units=units, models=model_specs, gen_params=gen,
                base_seed=base_seed, prompts=prompts_by_key,
                candidates=cands_by_key, config=config)
