# 歌尔杯赛题版 MetaGPT 使用说明

本文档说明如何使用本仓库中已修改的 MetaGPT，完成《基于 AI Agent 的 IT 功能全链路自动化开发系统》赛题要求。

## 1. 本版本做了什么

本版本不是另起一个外部系统，而是直接修改 MetaGPT 原生软件公司流程，使其默认使用以下多 Agent 链路：

```text
ProductManager -> Architect -> ProjectManager -> Engineer -> QaEngineer
```

对应赛题中的三个核心 Agent：

| 赛题节点 | MetaGPT 原生角色/动作 |
|---|---|
| 概要设计 Agent | `Architect` + `WriteDesign` |
| 代码生成 Agent | `Engineer` + `WriteCode` |
| 单元测试 Agent | `QaEngineer` + `WriteTest / RunCode / DebugError` |

运行后会额外生成赛题要求的目录和状态文件：

```text
docs/
├── 待生成/
└── 已生成/{batch_id}/
    ├── batch_status.json
    ├── execution_log.json
    ├── 概要设计/
    ├── 代码生成/
    └── 单元测试/
src/
tests/
```

## 2. 开源来源与改造边界

本系统基于开源项目 MetaGPT 修改开发：

```text
项目来源：https://github.com/FoundationAgents/MetaGPT.git
开源协议：MIT License
本地仓库：D:\goertek-hack\MetaGPT
```

本版本保留 MetaGPT 原有的 `Team / Role / Action / Memory / Context` 协作机制，主要改造点是：

- 让 `metagpt.software_company` 可直接读取 Markdown 产品规格说明书作为输入。
- 使用 MetaGPT 原生角色完成需求理解、概要设计、任务拆解、代码生成、测试生成。
- 增加赛题要求的批次目录、节点状态、执行日志、产物归档。
- 适配 DeepSeek OpenAI-compatible API，并修复 JSON 输出被截断或解析失败时导致流程中断的问题。
- 在 Windows 环境下修复日志编码、可选依赖导入、固定 SOP 循环等影响实际运行的问题。

本版本不是绕开 MetaGPT 另写一套脚本，也不是把代码一次性塞进 Prompt 生成；各节点的上下文通过 MetaGPT 工作区中的结构化文档、JSON、代码文件和测试文件逐步传递。

## 3. 系统架构说明

```text
Markdown 产品规格说明书
        |
        v
MetaGPT Team Orchestrator
        |
        +--> ProductManager：理解输入需求，形成 PRD
        |
        +--> Architect：基于 PRD 生成概要设计、接口设计、流程图
        |
        +--> ProjectManager：把概要设计拆解为开发任务
        |
        +--> Engineer：按任务生成应用源代码
        |
        +--> QaEngineer：基于代码和设计生成测试、运行测试、记录结果
        |
        v
赛题产物归档器 full_chain_artifacts
        |
        +--> docs/待生成/
        +--> docs/已生成/{batch_id}/batch_status.json
        +--> docs/已生成/{batch_id}/execution_log.json
        +--> docs/已生成/{batch_id}/概要设计/
        +--> docs/已生成/{batch_id}/代码生成/
        +--> docs/已生成/{batch_id}/单元测试/
        +--> src/
        +--> tests/
```

流程编排由 MetaGPT 原生 `Team` 负责，节点依赖由角色之间的消息、观察对象和动作触发关系控制；赛题要求的状态文件由 `metagpt/utils/full_chain_artifacts.py` 记录。当前采用自动模式：上游节点完成后，下游节点自动继续执行。

## 4. 环境要求

MetaGPT 原项目要求 Python 版本：

```text
Python >= 3.9, < 3.12
```

当前机器默认 Python 是 3.12，因此建议新建 Conda 环境：

```powershell
conda create -n metagpt-hack python=3.10 -y
conda activate metagpt-hack
```

进入 MetaGPT 目录：

```powershell
cd D:\goertek-hack\MetaGPT
```

安装依赖：

```powershell
python -m pip install -U pip
python -m pip install -e .
```

如果安装中出现个别依赖问题，可再执行：

```powershell
python -m pip install -r requirements.txt
```

## 5. 配置 DeepSeek API

本版本支持通过环境变量配置 OpenAI-compatible API。使用 DeepSeek 时：

```powershell
$env:METAGPT_API_KEY="你的 API Key"
$env:METAGPT_BASE_URL="https://api.deepseek.com"
$env:METAGPT_MODEL="deepseek-v4-flash"
$env:METAGPT_MAX_TOKEN="12000"
$env:PYTHONIOENCODING="utf-8"
```

也兼容以下变量名：

```text
AGENTDEV_API_KEY / OPENAI_API_KEY
AGENTDEV_BASE_URL / OPENAI_BASE_URL
AGENTDEV_MODEL / OPENAI_MODEL
AGENTDEV_MAX_TOKEN / OPENAI_MAX_TOKEN
```

建议不要把 API Key 写入代码或配置文件。

`METAGPT_MAX_TOKEN` 建议保持为 `12000` 或更高。`deepseek-v4-flash` 的返回中可能包含 reasoning tokens，如果仍使用 MetaGPT 默认 `4096`，复杂设计 JSON 容易被截断，导致 `JSONDecodeError: Unterminated string`。

### 5.1 配置高级 DebugError 模型

当同一个测试文件连续两次未通过时，`QaEngineer` 会让 `DebugError` 升级调用高级模型进行修复，修复后继续回到测试循环。默认高级模型配置为：

```powershell
$env:METAGPT_ADVANCED_MODEL="claude-opus-4-8"
$env:METAGPT_ADVANCED_BASE_URL="https://api.xstx.info"
$env:METAGPT_ADVANCED_API_KEY="你的高级模型 API Key"
```

如果不设置 `METAGPT_ADVANCED_API_KEY`，系统会降级使用当前主模型，不会直接中断流程。可选配置：

```powershell
$env:METAGPT_ADVANCED_MAX_TOKEN="12000"
$env:METAGPT_QA_MAX_ROUNDS="12"
```

## 6. 设置赛题输出根目录

为了让生成结果输出到 `D:\goertek-hack`，设置：

```powershell
$env:METAGPT_FULL_CHAIN_ROOT="D:\goertek-hack"
```

如果不设置，默认会输出到当前命令所在目录。

## 7. 运行赛题验证用例

使用赛题提供的产品规格说明书作为输入：

```powershell
metagpt "D:\goertek-hack\试题成果验证测试用例---产品规格说明书(员工临时车辆预约程序).md"
```

也可以用 Python 模块方式运行：

```powershell
python -m metagpt.software_company "D:\goertek-hack\试题成果验证测试用例---产品规格说明书(员工临时车辆预约程序).md"
```

运行过程会自动执行：

1. 读取 Markdown 产品规格说明书
2. ProductManager 生成产品需求文档
3. Architect 生成概要设计/系统设计
4. ProjectManager 拆解开发任务
5. Engineer 生成源码
6. QaEngineer 生成并运行单元测试
7. 同步输出到赛题要求目录

## 8. 查看输出结果

运行完成后，检查：

```text
D:\goertek-hack\docs\待生成\
D:\goertek-hack\docs\已生成\{batch_id}\batch_status.json
D:\goertek-hack\docs\已生成\{batch_id}\execution_log.json
D:\goertek-hack\docs\已生成\{batch_id}\概要设计\
D:\goertek-hack\docs\已生成\{batch_id}\代码生成\
D:\goertek-hack\docs\已生成\{batch_id}\单元测试\
D:\goertek-hack\src\
D:\goertek-hack\tests\
```

一次成功运行的 `batch_status.json` 应该满足：

```text
status = completed
current_node = null
nodes.design.status = completed
nodes.code_generation.status = completed
nodes.unit_test.status = completed
```

`batch_status.json` 中会记录：

- `batch_id`
- 输入产品规格说明书
- 当前批次状态
- 当前节点
- 三个节点的状态、开始/结束时间、输入文件、输出文件、质量检查结果

`execution_log.json` 中会记录：

- 批次创建
- 节点开始
- 节点完成
- 节点失败
- 批次结束

当前已验证成功的批次示例：

```text
D:\goertek-hack\docs\已生成\vehicle_reservation_demo_final\
```

该批次已完成概要设计、代码生成和单元测试三个节点，并同步源码到：

```text
D:\goertek-hack\src\
D:\goertek-hack\tests\
```

可运行以下命令验证测试目录中的结构测试：

```powershell
node D:\goertek-hack\tests\test_generated_project_structure.js
```

预期输出：

```text
validated 22 generated files
```

## 9. 批次 ID

如果运行命令没有指定项目名，系统会根据输入文件名自动生成批次 ID。

如需指定项目名，可使用 MetaGPT 原参数：

```powershell
metagpt "D:\goertek-hack\试题成果验证测试用例---产品规格说明书(员工临时车辆预约程序).md" --project-name vehicle_reservation_demo
```

此时输出目录会包含：

```text
D:\goertek-hack\docs\已生成\vehicle_reservation_demo\
```

## 10. 增量与失败恢复

MetaGPT 原生支持增量开发与恢复参数：

```powershell
metagpt "新的需求说明" --project-path "已有项目路径" --inc
```

恢复已有 Team 状态：

```powershell
metagpt "需求说明" --recover-path "workspace\storage\team"
```

当前版本已经将失败节点写入 `batch_status.json`，但尚未提供一个单独的 `retry-node design/code_generation/unit_test` 命令。需要重试时，优先使用 MetaGPT 原生的 `--inc`、`--project-path`、`--reqa-file`、`--recover-path`。

## 11. DeepSeek JSON 输出测试

仓库中提供了一个独立测试脚本，用于确认 DeepSeek 是否能按要求输出严格 JSON：

```powershell
python scripts\test_deepseek_json_strict.py --repeat 1 --max-tokens 2500
```

输出会保存到：

```text
D:\goertek-hack\MetaGPT\.json_probe_outputs\
```

已验证结果：

```text
max_tokens=2500: 5/5 passed
max_tokens=800: 部分失败，finish_reason=length，说明 JSON 被截断
```

因此本系统中对 JSON Action 做了两项兼容：

- JSON 模式使用非流式调用，避免 Windows 控制台编码或流式截断干扰。
- OpenAI-compatible 调用透传 `response_format={"type":"json_object"}`，并配合 `METAGPT_MAX_TOKEN=12000` 降低 JSON 截断风险。

## 12. 赛题要求符合性检查

| 赛题要求 | 当前实现情况 | 说明 |
|---|---|---|
| 输入 Markdown 产品规格说明书 | 已支持 | `metagpt` 命令可直接传入 `.md` 文件路径 |
| 多 Agent 协作 | 已支持 | 使用 MetaGPT 原生 `ProductManager / Architect / ProjectManager / Engineer / QaEngineer` |
| 概要设计 Agent | 已支持 | `Architect + WriteDesign` 产出概要设计相关 JSON/Mermaid 文档 |
| 代码生成 Agent | 已支持 | `Engineer + WriteCode` 产出 Node/React/CSV 示例系统源码 |
| 单元测试 Agent | 已支持 | `QaEngineer` 会生成并运行多语言测试；连续失败两次后 `DebugError` 可升级到高级模型修复 |
| 流程编排和依赖 | 已支持 | MetaGPT `Team` 自动编排，顺序推进各角色动作 |
| 状态 JSON | 已支持 | `batch_status.json` 记录批次和节点状态 |
| 执行日志 JSON | 已支持 | `execution_log.json` 记录节点开始、完成、失败和批次结束 |
| 目录结构 | 已支持 | 输出到 `docs/待生成`、`docs/已生成/{batch_id}`、`src`、`tests` |
| 增量执行 | 部分支持 | 使用 MetaGPT 原生 `--inc / --project-path / --recover-path`；尚无单独节点重试 CLI |
| 质量检查 | 部分支持 | 当前为产物存在性和节点完成检查，不是完整覆盖率评分 |

## 13. 当前已知限制

1. 必须先安装 MetaGPT 依赖，否则会出现类似错误：

```text
ModuleNotFoundError: No module named 'semantic_kernel'
```

2. 当前默认 Python 3.12 不符合 MetaGPT 原要求，建议使用 Python 3.10 或 3.11。

3. `quality_check_result` 目前记录的是节点是否产生产物的基础检查结果，不是严格的覆盖率统计。

4. 单节点显式重试 CLI 尚未补齐，但 MetaGPT 原生增量和恢复机制仍可使用。

5. MetaGPT 原生 `QaEngineer/WriteTest` 主要面向 Python 项目。当前赛题生成的是 Node/React 项目时，系统会补充一个可运行的 Node 静态结构测试 `tests/test_generated_project_structure.js`，用于验证生成源码存在且非空。它不是完整业务接口覆盖率测试。

6. 生成的 Node/React 项目代码由 MetaGPT 产出，可能还需要补齐 `package.json`、安装前端/后端依赖后才能作为完整 Web 应用启动。赛题链路验证重点是自动生成概要设计、源码、测试与状态追踪。

## 14. 推荐演示流程

```powershell
conda activate metagpt-hack
cd D:\goertek-hack\MetaGPT

$env:METAGPT_API_KEY="你的 API Key"
$env:METAGPT_BASE_URL="https://api.deepseek.com"
$env:METAGPT_MODEL="deepseek-v4-flash"
$env:METAGPT_MAX_TOKEN="12000"
$env:PYTHONIOENCODING="utf-8"
$env:METAGPT_FULL_CHAIN_ROOT="D:\goertek-hack"

metagpt "D:\goertek-hack\试题成果验证测试用例---产品规格说明书(员工临时车辆预约程序).md" --project-name vehicle_reservation_demo
```

然后展示：

```text
D:\goertek-hack\docs\已生成\vehicle_reservation_demo\
D:\goertek-hack\src\
D:\goertek-hack\tests\
```

重点讲解：

- 多 Agent 分工
- MetaGPT 原生 Team/Role/Action 协作
- 从 Markdown 需求到概要设计、源码、单元测试的自动链路
- `batch_status.json` 和 `execution_log.json` 的状态追踪

演示前可先执行：

```powershell
python -m compileall metagpt\actions\action_node.py metagpt\provider\openai_api.py metagpt\config2.py metagpt\software_company.py metagpt\roles\di\role_zero.py metagpt\utils\full_chain_artifacts.py
python scripts\test_deepseek_json_strict.py --repeat 1 --max-tokens 2500
```

## 15. 提交前检查清单

提交或录制演示视频前，建议逐项确认：

- 已使用 Python 3.10 或 3.11 环境安装依赖。
- 已设置 `METAGPT_API_KEY`、`METAGPT_BASE_URL`、`METAGPT_MODEL`、`METAGPT_MAX_TOKEN`。
- 已运行员工临时车辆预约程序规格说明书测试用例。
- `batch_status.json` 中批次状态为 `completed`。
- `execution_log.json` 中存在 `batch_finished` 记录。
- `docs/已生成/{batch_id}/概要设计`、`代码生成`、`单元测试` 均有产物。
- `src/` 中有生成的应用源码。
- `tests/` 中有生成的测试文件，并且结构测试可执行。
- README 中已经填写真实团队成员分工。
- 演示视频中展示了从规格说明书输入到生成应用系统产物的完整过程。

## 16. 团队成员分工

请在最终提交前把下面表格替换为真实成员信息。不要保留占位内容提交。

| 成员 | 分工 |
|---|---|
| 成员 A | MetaGPT 框架调研、流程编排改造、Agent 链路设计 |
| 成员 B | DeepSeek API 配置、JSON 输出稳定性测试、运行环境搭建 |
| 成员 C | 赛题产物目录、状态文件、执行日志、验证脚本开发 |
| 成员 D | 需求测试用例验证、演示视频录制、文档整理 |
