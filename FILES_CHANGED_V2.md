# V2 文件修改清单

以修改前的 baseline_manifest.json 为基准。原仓库在此工作树中已是未跟踪状态，因此使用文件 hash 比对，不依赖 git diff。原测试、原评测数据及原历史报告均未删除或修改。

## 修改原文件

- [.dockerignore](.dockerignore)
- [.env.example](.env.example)
- [Dockerfile](Dockerfile)
- [Makefile](Makefile)
- [README.md](README.md)
- [pyproject.toml](pyproject.toml)
- [src/supplychain_agent/api.py](src/supplychain_agent/api.py)
- [uv.lock](uv.lock)

## 新增代码与工具

- [scripts/verify_v2_evidence.py](scripts/verify_v2_evidence.py)

- [scripts/replay_v2.py](scripts/replay_v2.py)
- [scripts/report_v2.py](scripts/report_v2.py)
- [scripts/smoke_v2.py](scripts/smoke_v2.py)
- [src/supplychain_agent/v2/__init__.py](src/supplychain_agent/v2/__init__.py)
- [src/supplychain_agent/v2/agent.py](src/supplychain_agent/v2/agent.py)
- [src/supplychain_agent/v2/api.py](src/supplychain_agent/v2/api.py)
- [src/supplychain_agent/v2/contracts.py](src/supplychain_agent/v2/contracts.py)
- [src/supplychain_agent/v2/database.py](src/supplychain_agent/v2/database.py)
- [src/supplychain_agent/v2/evaluation.py](src/supplychain_agent/v2/evaluation.py)
- [src/supplychain_agent/v2/model.py](src/supplychain_agent/v2/model.py)
- [src/supplychain_agent/v2/policies/approval.md](src/supplychain_agent/v2/policies/approval.md)
- [src/supplychain_agent/v2/policies/budget.md](src/supplychain_agent/v2/policies/budget.md)
- [src/supplychain_agent/v2/policies/emergency.md](src/supplychain_agent/v2/policies/emergency.md)
- [src/supplychain_agent/v2/policies/lead.md](src/supplychain_agent/v2/policies/lead.md)
- [src/supplychain_agent/v2/policies/moq.md](src/supplychain_agent/v2/policies/moq.md)
- [src/supplychain_agent/v2/policies/service.md](src/supplychain_agent/v2/policies/service.md)
- [src/supplychain_agent/v2/policies/supplier.md](src/supplychain_agent/v2/policies/supplier.md)
- [src/supplychain_agent/v2/retrieval.py](src/supplychain_agent/v2/retrieval.py)
- [src/supplychain_agent/v2/tools.py](src/supplychain_agent/v2/tools.py)
- [src/supplychain_agent/v2/trace.py](src/supplychain_agent/v2/trace.py)

## 新增测试

- [tests/test_v2_agent.py](tests/test_v2_agent.py)
- [tests/test_v2_evaluation.py](tests/test_v2_evaluation.py)
- [tests/test_v2_retrieval.py](tests/test_v2_retrieval.py)
- [tests/test_v2_tools_db.py](tests/test_v2_tools_db.py)

## 新增文档与数据

- [AGENT_V2_AUDIT.md](AGENT_V2_AUDIT.md)
- [AGENT_V2_FINAL_REPORT.md](AGENT_V2_FINAL_REPORT.md)
- [FILES_CHANGED_V2.md](FILES_CHANGED_V2.md)
- [RESUME_AGENT_V2_EVIDENCE.md](RESUME_AGENT_V2_EVIDENCE.md)
- [evaluation/PROTOCOL_V2.md](evaluation/PROTOCOL_V2.md)
- [evaluation/dev_v2.jsonl](evaluation/dev_v2.jsonl)
- [evaluation/heldout_v2.jsonl](evaluation/heldout_v2.jsonl)
- [evaluation/report_v2.md](evaluation/report_v2.md)
- [evaluation/results_v2.json](evaluation/results_v2.json)
- [evaluation/retrieval_dev_v2.jsonl](evaluation/retrieval_dev_v2.jsonl)
- [evaluation/retrieval_heldout_v2.jsonl](evaluation/retrieval_heldout_v2.jsonl)

## 新增运行证据

- [evaluation/evidence/final_gate.json](evaluation/evidence/final_gate.json)

- [evaluation/evidence/baseline_manifest.json](evaluation/evidence/baseline_manifest.json)
- [evaluation/evidence/docker.json](evaluation/evidence/docker.json)
- [evaluation/evidence/heldout_label_validation.json](evaluation/evidence/heldout_label_validation.json)
- [evaluation/evidence/http_smoke.json](evaluation/evidence/http_smoke.json)
- [evaluation/evidence/integrity.json](evaluation/evidence/integrity.json)
- [evaluation/evidence/pre_heldout_freeze.json](evaluation/evidence/pre_heldout_freeze.json)
- [evaluation/evidence/pytest-baseline.xml](evaluation/evidence/pytest-baseline.xml)
- [evaluation/evidence/pytest-final.xml](evaluation/evidence/pytest-final.xml)
- [evaluation/evidence/pytest-phase1.xml](evaluation/evidence/pytest-phase1.xml)
- [evaluation/evidence/pytest-phase2.xml](evaluation/evidence/pytest-phase2.xml)
- [evaluation/evidence/pytest-phase3.xml](evaluation/evidence/pytest-phase3.xml)
- [evaluation/evidence/pytest-phase4.xml](evaluation/evidence/pytest-phase4.xml)
- [evaluation/evidence/pytest-phase5.xml](evaluation/evidence/pytest-phase5.xml)
- [evaluation/evidence/pytest-phase6.xml](evaluation/evidence/pytest-phase6.xml)
- [evaluation/evidence/pytest-phase7.xml](evaluation/evidence/pytest-phase7.xml)
- [evaluation/evidence/test_summary.json](evaluation/evidence/test_summary.json)
- [evaluation/evidence/wheel.json](evaluation/evidence/wheel.json)
- [evaluation/runs_v2/dev_demo.json](evaluation/runs_v2/dev_demo.json)
- [evaluation/runs_v2/dev_demo_final.json](evaluation/runs_v2/dev_demo_final.json)
- [evaluation/runs_v2/dev_llm_final.json](evaluation/runs_v2/dev_llm_final.json)
- [evaluation/runs_v2/dev_llm_initial.json](evaluation/runs_v2/dev_llm_initial.json)
- [evaluation/runs_v2/dev_llm_v2.json](evaluation/runs_v2/dev_llm_v2.json)
- [evaluation/runs_v2/dev_llm_v3.json](evaluation/runs_v2/dev_llm_v3.json)
- [evaluation/runs_v2/heldout_demo.json](evaluation/runs_v2/heldout_demo.json)
- [evaluation/runs_v2/heldout_llm.json](evaluation/runs_v2/heldout_llm.json)
- [evaluation/runs_v2/retrieval_dev.json](evaluation/runs_v2/retrieval_dev.json)
- [evaluation/runs_v2/retrieval_heldout.json](evaluation/runs_v2/retrieval_heldout.json)
- [reports/demo.svg](reports/demo.svg)
- [reports/v2-regression-rules-dev/report.json](reports/v2-regression-rules-dev/report.json)
- [reports/v2-regression-rules-dev/report.md](reports/v2-regression-rules-dev/report.md)
- [reports/v2-regression-rules-test/report.json](reports/v2-regression-rules-test/report.json)
- [reports/v2-regression-rules-test/report.md](reports/v2-regression-rules-test/report.md)
