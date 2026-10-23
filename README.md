# Open-Lottery-AI

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white" alt="PyTorch">
  <img src="https://img.shields.io/badge/Vue%203-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
</p>

> 基于 **FastAPI + PyTorch + Transformer + Vue 3** 的**时序序列建模与深度学习工程实践**项目。以公开历史编号数据为样本，验证多标签分类、序列模型、自我学习闭环等算法在弱信号时序数据上的建模效果。

> ⚠️ **重要免责声明**
> - 本项目仅用于机器学习、时序数据分析与软件工程技术的学习交流，**不构成任何投资或决策建议**。
> - 样本数据为**独立随机事件**，历史数据不包含未来结果的可预测信息，本项目模型输出的概率/号码**不具备任何实际价值**，**严禁用于任何商业或决策用途**。
> - 本项目不提供任何销售、交易、代购、代投类服务，请遵守所在地区法律法规。

## 🆕 最近更新

- **🔬 复试最优方案（GA 遗传算法优化）**：基于 AI 预测频率分数，使用遗传算法对每个复试档位独立进化号码池；融合热号、冷门反向变异、区间覆盖、奇偶均衡、历史回测命中、档位差异化等 5 维适应度，自动展开 7+1 / 8+2 / 12+4 等全档位组合并入库存档。
- **🎯 本期模型过滤**：`/models/list?current_period=true` 仅返回最近一期开奖号发布之后训练的本期模型，避免用旧数据推断。
- **💰 复试命中奖金评估**：自动按官方固定奖级规则计算历史命中金额、奖级分布与浮动奖注数，回填 `forecast_analysis` 表。

## 🛠 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | FastAPI (异步, OpenAPI) |
| 深度学习 | PyTorch `nn.TransformerEncoder` + 多标签分类（BCEWithLogitsLoss） |
| 异步任务 | RabbitMQ + Celery |
| 数据库 | MySQL 8.0 + SQLAlchemy 2.0 (asyncmy 异步 / pymysql 同步) |
| 缓存 / 状态 | Redis（Celery 结果后端 + 独立异步缓存客户端） |
| 数据处理 | Pandas + NumPy + scikit-learn (StandardScaler) |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + ECharts |
| 部署 | Docker Compose |

## ✨ 核心特性

### 🤖 深度学习建模

**多标签分类训练**（非回归）：对每个可能号码输出概率，用 BCEWithLogitsLoss + 正样本权重补偿（pos_weight）训练
- 推断时从概率分布取**确定性 Top-K 号码**（前段取概率最高的 6 个、后段取最高的 1/2 个，升序返回，保证可复现）
- 训练中实时评估 Top-K **命中率**（技术评估指标，指模型输出与历史样本的吻合比例；前段/后段/综合，按号码个数加权）
- 质量评分公式：`0.7 × avg(选中前段概率) + 0.3 × avg(选中后段概率)`，clip 到 [0.1, 1.0]

**特征工程**：数据库全字段 + 号码频率 + 移动窗口统计
- 数据集 A：99 维特征（50 基础 + 33 前段频率 + 16 后段频率）+ 49 维 multi-hot 目标 = 148 列
- 数据集 B：99 维特征（52 基础 + 35 前段频率 + 12 后段频率）+ 47 维 multi-hot 目标 = 146 列

**模型结构**：`LotteryClassifier` — 双头分类（前段头 + 后段头），序列特征聚合（last + mean pooling），3 层 MLP 分类头

**训练流程**：验证集时间切分 → Early Stopping (patience ≥ 20，按**验证命中率**而非 loss 选 Best Model) → CosineAnnealingLR → 梯度裁剪 → fp16 混合精度 → Best Model → 训练曲线 + 命中率落盘 JSON

**训练细节**：
- 正样本权重 `pos_weight = (号码空间 - 每注号码数) / 每注号码数`，补偿多标签正负不均衡
- 命中率 = Top-K 模型输出号码与真实号码交集 / 真实号码数（技术吻合度指标）；综合命中率按前后段号码个数加权
- 标准化器 `StandardScaler` 仅在训练段拟合（防数据泄漏），multi-hot 目标不参与标准化
- 单模型回测 GPU 批处理：所有回测期窗口打包一次前向，单模型 <1 秒

**训练脚本**：`batch_train_seqlen.py` 无限循环随机超参搜索，30 秒提交一个任务，CSV 记录 best_val_loss / best_hit_rate 等

### 🔄 自我学习闭环

```
训练模型 → 逐期回测模型吻合度 → 写入 model_score 表
                ↓（反馈）
  ┌─────────────┴──────────────┐
  │ 智能选模：按回测表现选模型     │
  │ 集成推断：表现加权融合 Top-5  │ → 推断号码入库
  └────────────────────────────┘
```

- **回测服务** (`backtest_service.py`)：逐期 walk-forward 回测，30 期窗口批量前向推理，40 个模型仅需 ~6 秒
- **集成推断** (`ensemble_service.py`)：按回测表现加权融合 Top-5 模型概率分布，生成推断号码
- **模型评分** (`model_score` 表)：记录每个模型的前段/后段/综合命中率（技术吻合度），驱动智能选模

**训练侧反馈（P1-P4 自我强化）**：回测结果不仅用于选模，还反向注入下一轮训练：

| 阶段 | 机制 | 实现 |
|------|------|------|
| **P1 困难期次加权** | Top-K 模型平均命中率 < 0.3 的期次，训练样本权重 ×2.0 | `get_hard_periods()` → sample_weights |
| **P2 超参元学习** | 统计 Top-20 模型的 epochs/batch_size/lr 分布，供新训练偏向采样 | `get_top_hyperparams()` |
| **P3 弱点号码加权** | 未命中率 > 0.7 的号码，对应列 loss 权重 ×2.0 | `get_weak_numbers()` → class_weights |
| **P4 自适应淘汰** | 回测 hit_total < 阈值的模型优先从磁盘删除（保留本期模型 + Top 榜单） | `cleanup_old_models(low_score_threshold=...)` |

困难期次 / 弱点号码 / 超参分布均带 1 小时进程内缓存，避免每次训练重复计算。

### 🎯 一键智能推断流水线

推断页主按钮「🚀 一键智能推断」串联自我学习闭环（**技术验证用途，模型输出仅作算法效果展示，严禁用于商业或决策用途**），四步自动完成：

```
提交回测任务（Celery 后台评分，提交即走不阻塞）
        ↓
智能选模 → 批量并行推断（全部选中模型一次请求）
        ↓
集成融合（按回测表现加权 Top-5；首次运行先等回测出分再融合）
        ↓
自动生成复试方案（GA 优化全部档位并写入 forecast_analysis）
```

- **批量并行推断** `POST /predict/batch/{lottery_type}`（流式版 `/predict/batch-stream/`）：数据只加载一次，torch 推理经 `asyncio.to_thread` 丢线程池 16 路并行（单推理单线程 `torch.set_num_threads(1)` 避免核数超订，不阻塞事件循环），NDJSON 逐模型推送实时进度（`X-Accel-Buffering: no` 防代理缓冲，前端按 `\n` 切分解析兼容半包粘包）；结果单会话批量入库
- **前端实时反馈**：进度条展示真实进度（已完成/总数、成功/失败计数与百分比），结果卡片完成一个追加一个；请求中断时未完成模型统一标记失败；结果区分页渲染（每页 30 张）避免大量 DOM 卡顿
- **模型缓存**：模型权重 / StandardScaler / meta 按 `(路径, mtime)` 缓存且为**有界 LRU**（权重上限 256 个，数千模型不全量常驻防 OOM），重训覆盖自动失效，缓存加载加线程锁双重检查；集成服务复用同一缓存，成员模型并行推理
- **大批量入库**：目标日期已有记录一次查全、内存匹配后批量 insert/update + 单次 commit，避免数千次数据库往返
- **分析页性能**（`/analysis/today`、`/data/similarity`）：历史相似度从「逐条 set 重建的 O(F×H) / O(N²) 双重循环」改为**号码位掩码 + numpy 向量化 popcount**（号码 n → bit n-1，交集即位与计数），2000+ 期历史 × 数千推断亚秒级完成，结果与原算法逐位一致；动态阈值与全量自相似结果按最新编号缓存（新批次导入自动失效）；全组合表 ID 由逐条 N 次 session 查询改为单会话元组 IN 分块批量查询；相似度标记落库走 Core `update() + case()` 批量 UPDATE（每 200 行一批，由编译器原生绑定参数，仅值变化时执行）；CPU 计算均经 `asyncio.to_thread` 不阻塞事件循环
- **回测容错**：已有评分时直接用旧评分集成、回测后台静默刷新；首次运行自动等待回测完成；等待有 15 分钟上限（worker 未启动时明确报错而非无限轮询）

### 🔬 复试最优方案（GA 遗传算法优化）

> 仅作为算法工程实验展示，模型输出号码**不具备任何实际价值**，严禁用于商业或决策用途。

由 `fushi_service.py` + `ga_optimizer.py` 驱动，在预测入库后自动生成多档复试方案并写入 `forecast_analysis` 表：

```
AI 预测频率分数（所有号码 0~1 分）
        ↓
遗传算法（每档独立进化）
  - 初始种群：70% 热号 + 30% 冷门
  - 适应度：0.35 频率 + 0.25 区间覆盖/奇偶均衡 + 0.25 近 30 期回测命中 - 0.10 档位重合 - 0.05 金额爆炸
  - 反向变异：20% 概率将基因替换为低频率冷门号码
  - 精英保留 + 80 代进化
        ↓
按档位 C(n红, k红) × C(n蓝, k蓝) 展开全部组合注
        ↓
写入 forecast_analysis（含 optimization_meta GA 元信息）
```

- **档位矩阵**：双色球 7+1 ~ 12+4 共 24 档，大乐透 6+2 ~ 11+4 共 18 档，注数/金额严格按官方复试规则。
- **触发时机**：一键智能预测 / 批量预测 / 单模型预测完成后自动写入；analysis 页只读展示，hit-analysis 页读取命中回填。
- **历史命中评估**：开奖号公布后自动按官方奖级规则计算奖级、固定奖金、浮动奖注数并回填。

### 📊 统计分析与编号核对

- **统计图表** (`GET /data/trend/{lottery_type}?periods=100`)：前段/后段号码频率、当前间隔、高频/低频号码 TOP5、和值/跨度趋势、奇偶/大小分布，前端 ECharts 多图联动
- **编号核对** (`/hit-analysis/*`)：新批次数据导入后选择历史批次，将该批次全部推断记录与实际数据逐条核对匹配数并按规则匹配等级判定（技术吻合度验证），降序展示
- **历史相似度分析**：推断号码与全部历史数据做 Jaccard 相似度对比，动态阈值（均值+1σ）计算相似度；**不剔除记录**，仅将 `max_similarity` / `matched_history_issue` 落库标记供展示，编号核对全部推断参与统计
- **全组合 ID 查询**：推断号码在 `ssq_all` / `dlt_all` 全组合表中查找对应 ID
- **历史自相似度分析**：每期数据与所有上期对比，输出分布统计（均值/中位数/TOP 10/直方图）

## 📂 目录结构

```
open-lottery-ai/
├── app/                               # 后端 (FastAPI)
│   ├── api/routes/                     # 路由
│   │   ├── health.py                   # 健康检查
│   │   ├── data.py                     # 历史数据 + 统计图表 + 相似度分析
│   │   ├── train.py                    # 训练提交 + 状态查询
│   │   ├── predict.py                  # 推断 + 批量推断 + 回测 + 集成 + 榜单
│   │   ├── models.py                   # 模型文件管理
│   │   ├── analysis.py                 # 推断分析 + 相似度标记
│   │   ├── hit_analysis.py             # 编号核对（规则匹配等级判定）
│   │   └── agent.py                    # AI Agent 对话（超参/选模推荐）
│   ├── core/                           # 基础设施
│   │   ├── config.py                   # 配置管理（pydantic-settings，按 APP_ENV 选 .env）
│   │   ├── database.py                 # 异步/同步双引擎 + 会话工厂
│   │   ├── redis_client.py             # Redis 异步客户端
│   │   ├── celery_app.py               # Celery 应用配置
│   │   ├── migrations.py               # 幂等迁移（补齐列/索引/唯一约束）
│   │   └── agent_templates.py          # Agent system/user prompt 模板
│   ├── models/                         # SQLAlchemy ORM
│   │   ├── ssq_history.py / dlt_history.py     # 数据集 A/B 历史数据
│   │   ├── ssq_forecast.py / dlt_forecast.py   # 推断记录
│   │   └── model_score.py                      # 模型回测评分
│   ├── schemas/                        # Pydantic 请求/响应
│   ├── services/
│   │   ├── data_loader.py              # 数据加载 + 特征工程（全字段 + 频率 + multi-hot）
│   │   ├── transformer_model.py        # LotteryClassifier 分类模型
│   │   ├── trainer.py                  # 训练器 (BCE Loss + Early Stopping + 命中率 + fp16 + P1~P4)
│   │   ├── predictor.py                # 推断器 (确定性 Top-K + 批量并行 + LRU 缓存)
│   │   ├── backtest_service.py         # 逐期回测 + 评分写入 model_score + 困难期次/弱点号码分析
│   │   ├── ensemble_service.py         # 回测表现加权融合 Top-K 集成推断
│   │   ├── analysis_service.py         # 推断分析 + 动态阈值相似度标记 + 标记批量落库
│   │   ├── fushi_service.py            # 复试最优方案：频率计算 + 档位独立 GA 优化 + 组合展开 + 落库
│   │   ├── ga_optimizer.py             # 遗传算法核心（编码/5维适应度/交叉/变异/精英保留）
│   │   ├── hit_analysis_service.py     # 编号核对（推断 vs 实际逐条比对 + 匹配等级）
│   │   ├── agent_service.py            # AI Agent (DeepSeek + RAG 历史任务向量检索)
│   │   ├── number_utils.py             # 号码提取统一工具
│   │   └── fetch_service.py            # 数据抓取调用
│   ├── scripts/
│   │   ├── fetch_ssq_incremental.py    # 数据集 A 增量抓取
│   │   ├── fetch_dlt_incremental.py    # 数据集 B 增量抓取
│   │   ├── generate_ssq_all.py         # 生成数据集 A 全组合表
│   │   └── generate_dlt_all.py         # 生成数据集 B 全组合表
│   ├── tasks/training_jobs.py           # Celery 任务 (start_training / run_backtest / run_full_pipeline)
│   └── main.py                         # 入口
├── lottery-ui/                        # Vue3 前端
│   └── src/views/
│       ├── dashboard/                  # 仪表盘
│       ├── data/                       # 数据管理 + 统计图表 (TrendAnalysis.vue) + 相似度分析
│       ├── train/                      # 模型训练
│       ├── predict/                    # 一键智能推断 + 回测 + 集成（推断完成后自动生成复试）
│       ├── analysis/                   # 推断分析 + 复试方案展示
│       └── hit-analysis/               # 编号核对（匹配明细）+ 复试命中展示
├── models/{ssq,dlt}/                   # 训练产物（根目录，按数据集分目录）
│   ├── {run_id}.pt                     # 模型权重 (history.json / meta.json / scaler.joblib 配套)
│   ├── {lottery}_final.pt              # 最新 Best Model
│   ├── {lottery}_final_meta.json       # 元信息 (model_type / input_dim / num_red / hit_rate ...)
│   ├── {lottery}_final_scaler.joblib   # 标准化器（仅特征列）
│   └── batch_train_results.csv         # 批量训练结果记录
├── sql/open-lottery.sql                # 建表脚本
├── tests/test_pure_logic.py            # 纯逻辑单元测试
├── batch_train_seqlen.py               # 无限循环随机超参搜索脚本
├── auto_train.bat                      # Windows 启动批量训练脚本
├── docker-compose.yml                  # MySQL / Redis / RabbitMQ
├── requirements.txt
└── .env.development / .env.production
```

## 🏗 系统架构

```
Vue3 前端 ──HTTP/NDJSON──► FastAPI ──发布──► RabbitMQ ──消费──► Celery Worker
     │                        │                                      │
     │                        ├── MySQL (history + forecast + model_score)
     │                        ├── Redis (Celery 结果后端 + 缓存客户端)
     │                        └── models/ (模型文件读写)
     │
     └── 页面: 仪表盘 / 数据管理(统计图表) / 训练 / 推断(一键流水线) / 分析 / 编号核对
```

**数据流**：数据抓取 → MySQL → 前端提交训练参数 → Celery 异步训练 → 模型落盘 `models/` → 批量推断（概率 Top-K 号码）→ 推断结果存 `*_forecast` → 回测验证 → 表现写入 `model_score` →（反馈）训练侧 P1~P4 加权 + 集成推断 / 智能选模 → 新批次数据导入后逐条核对匹配等级

**数据库双引擎**：FastAPI 请求走 `asyncmy` 异步引擎；Celery Worker 与 Agent 走 `pymysql` 同步引擎（`sync_engine`）。

**幂等迁移**：启动时 `run_migrations()` 自动补齐缺失列（`is_removed` / `max_similarity` / `matched_history_issue`）与索引（含 forecast 表唯一约束建前先去重），无需手动 ALTER TABLE。

**非发布日处理**：通过 `LOTTERY_HOLIDAYS` 配置（逗号分隔 ISO 日期），结果发布日计算自动跳过非发布期（最多向后查找 30 天，覆盖长假等）。

## 🚀 快速开始

```bash
# 1. 启动依赖
docker-compose up -d
docker exec -i lottery-mysql mysql -uroot -p123456 < sql/open-lottery.sql

# 2. 配置环境变量（复制并修改）
cp .env.development .env   # 或直接编辑 .env.development / .env.production
# 关键项：MYSQL_* / REDIS_* / CELERY_BROKER_URL / MODEL_SAVE_DIR / DEVICE / DEEPSEEK_API_KEY

# 3. 抓取数据
python app/scripts/fetch_ssq_incremental.py
python app/scripts/fetch_dlt_incremental.py

# 4. 生成全组合表（可选，用于推断组合的全局 ID 查询；导入后需重启服务）
python app/scripts/generate_ssq_all.py
python app/scripts/generate_dlt_all.py

# 5. 启动后端（终端1）
conda activate pytorch
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 启动时 run_migrations() 会自动补齐缺失列（如 forecast_analysis.optimization_meta），无需手动 ALTER。

# 6. 启动 Worker（终端2）
conda activate pytorch
# Windows 必须用 threads 池：solo 池让训练任务占用主事件循环，会导致心跳阻塞/任务卡死
celery -A app.core.celery_app worker --loglevel=info --pool=threads -c 1 -Q celery

# 6b. 启动 Beat（终端4，可选）：启用自我进化定时调度时需要
celery -A app.core.celery_app beat --loglevel=info

# 7. 启动前端（终端3）
cd lottery-ui && npm run dev
```

访问：前端 http://localhost:8888 / API 文档 http://localhost:8000/docs / RabbitMQ http://localhost:15672 (guest/guest)

## 🔄 批量训练脚本

`batch_train_seqlen.py` 无限循环随机搜索最优超参，每 30 秒提交一个训练任务：

| 参数 | 随机范围 |
|------|---------|
| 数据集 | ssq / dlt |
| epochs | 50 ~ 200 |
| batch_size | 16 / 32 / 64 / 128 |
| lr | 1e-5 ~ 1e-3（对数均匀采样） |
| seq_len | 取数据量上限（trainer 自动确保 ≥ 500 条训练样本） |

- 启动时自动调用增量抓取脚本更新数据
- 提交后不等结果，30 秒后提交下一个（失败自动重试 3 次）
- CSV 追加记录到 `models/batch_train_results.csv`：lottery_type / epochs / batch_size / seq_len / lr / **best_val_loss** / **best_hit_rate** / best_epoch / final_hit_rate / input_dim / run_id / status

Windows 双击 `auto_train.bat` 即可启动。

## 🧬 自我进化闭环（自动定时）

Celery Beat 每日定时触发任务 `run_self_evolution`，在数据更新后自动跑完一轮完整进化：

**检测新数据 → 回测打分 → 按高表现模型超参采样(P2) → 批量训练 N 个模型 → 复测 → 晋升榜单 → 集成推断入库**

- 任务内含「新数据闸门」：抓取后最新批次编号未变化则跳过本轮，避免空跑。
- 训练内部自动生效 P1（困难批次样本加权）与 P3（弱点编号 loss 加权）。
- 非破坏性：只新增模型，不删除历史模型（磁盘清理仍走 `cleanup_old_models`，默认关闭）。

配置项（`.env.*` 可覆盖）：

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `SELF_EVOLVE_ENABLED` | `true` | 是否注册 Beat 定时任务 |
| `SELF_EVOLVE_N_MODELS` | `15` | 每轮训练模型数（建议 10-20） |
| `SELF_EVOLVE_HOUR` / `SELF_EVOLVE_MINUTE` | `9` / `30` | 每日触发时刻（本地时区） |

- **定时**：需单独启动 Beat 进程（见启动步骤 6b）。
- **手动补跑**：`POST /train/evolve`，body `{"lottery_type":"ssq","n_models":2,"force":true}`，返回 `task_id`，可用 `/train/status/{task_id}` 查询进度。

> 提示：单轮训练 N 个模型耗时较长，worker 并发为 1 时按顺序执行；建议先用较小的 `SELF_EVOLVE_N_MODELS` 验证效果。

## 🗑 模型磁盘清理

`cleanup_old_models()` 按需清理模型三件套（`.pt` / `_scaler.joblib` / `_meta.json`），保留策略：
- **本期模型全部保留**：训练时间戳 ≥ 最近一期结果发布日 00:00 的模型
- **最近 N 个模型**：`MODEL_KEEP_LATEST`（默认 80）
- **回测榜单 Top M**：`MODEL_KEEP_TOP_SCORED`（默认 20）
- **P4 自适应淘汰**：`low_score_threshold > 0` 时，已回测且 `hit_total` 低于阈值的模型优先删除（Top 榜单不受影响）
- 所有 `*_final` 版本始终保留；`model_score` 表评分记录不受清理影响

## 📦 训练产物

每次训练生成 `{run_id}` 前缀的四件套：

| 文件 | 内容 |
|------|------|
| `{run_id}.pt` | 模型权重（Best Model，按验证命中率选择） |
| `{run_id}_scaler.joblib` | StandardScaler（仅特征列） |
| `{run_id}_history.json` | train_loss / val_loss / lr / hit_rate 曲线 |
| `{run_id}_meta.json` | model_type / 超参 / best_epoch / best_val_loss / best_hit_rate / input_dim / num_red / num_blue / pred_seq_len |

推断时自动读取 `{lottery}_final_meta.json`，若 `model_type == "classifier"` 则重建 `LotteryClassifier` 并用概率分布 Top-K 输出号码。

## 🔌 API 概览

| 路由 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/data/{lottery_type}` | GET | 历史编号数据（分页） |
| `/data/{lottery_type}/latest` | GET | 最新一期数据 |
| `/data/trend/{lottery_type}` | GET | 统计图表（频率/间隔/高频低频/和值跨度/奇偶大小，`periods` 30~500） |
| `/data/similarity/{lottery_type}` | GET | 历史自相似度分析（全量/可选批次数量） |
| `/train/start` | POST | 提交训练任务（Celery 异步） |
| `/train/evolve` | POST | 手动触发一轮自我进化闭环（Celery 异步） |
| `/train/status/{task_id}` | GET | 查询训练/回测任务状态 |
| `/predict/` | POST | 单模型推断 |
| `/predict/batch/{lottery_type}` | POST | 批量并行推断（多模型一次请求，线程池并行推理） |
| `/predict/batch-stream/{lottery_type}` | POST | 批量推断流式版（NDJSON 逐行推送单模型进度，前端实时进度条） |
| `/predict/backtest/{lottery_type}` | POST | 触发回测（Celery 异步，评分写 model_score） |
| `/predict/leaderboard/{lottery_type}` | GET | 模型回测得分榜单 |
| `/predict/ensemble/{lottery_type}` | POST | 集成推断（回测表现加权 Top-5 融合） |
| `/analysis/today` | GET | 推断分析（含相似度标记 + all 表 ID） |
| `/analysis/fushi/list` | GET | 复试方案列表（全部档位，按预测日期倒序） |
| `/analysis/fushi/evaluate` | POST | 对历史开奖后的复试方案批量评估命中与奖金 |
| `/hit-analysis/draws` | GET | 可做核对的历史批次列表（须有对标推断） |
| `/hit-analysis/detail` | GET | 单批次推断逐条匹配明细 + 匹配等级判定 |
| `/models/list` | GET | 模型文件列表（`current_period=true` 时仅返回最近一期结果发布后训练的本期模型） |
| `/agent/recommend-models/{lottery_type}` | GET | Agent 按回测表现智能推荐模型 |
| `/agent/recommend-hyperparams` | POST | Agent 推荐训练超参 |

## 🗄 数据模型

| 表 | 用途 | 关键字段 / 约束 |
|----|------|----------------|
| `ssq_history` / `dlt_history` | 历史结果数据（含预计算统计字段） | 编号唯一索引；号码列 + 和值/跨度/奇偶/大小/模3/连号等统计列 |
| `ssq_forecast` / `dlt_forecast` | 推断记录 | 唯一约束 `(forecast_date, model_version)`；`quality_score` / `is_removed` / `max_similarity` / `matched_history_issue` |
| `model_score` | 模型回测命中率（技术吻合度） | 唯一约束 `(lottery_type, model_name)`；复合索引 `(lottery_type, hit_total)` 支撑榜单查询 |
| `forecast_analysis` | 复试方案分析 | 唯一约束 `(lottery_type, forecast_date, pattern)`；JSON 字段 `red_pool` / `blue_pool` / `combo_detail` / `optimization_meta`；命中回填 `is_history_hit` / `prize_level` / `prize_amount` / `prize_detail` / `float_prize_count` |
| `ssq_all` / `dlt_all` | 全组合映射表（号码组合 → id） | 静态表，由 `generate_*_all.py` 离线生成，带进程内 LRU 缓存 |

## ⚙️ 配置项与环境变量

环境变量按 `APP_ENV` 选择 `.env.development` / `.env.production`（默认 development）：

| 变量 | 说明 |
|------|------|
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | MySQL 连接 |
| `REDIS_HOST/PORT/PASSWORD/DB` | Redis 连接 |
| `CELERY_BROKER_URL` | Celery broker（默认 RabbitMQ `amqp://guest:guest@localhost:5672//`） |
| `CELERY_RESULT_BACKEND` | 结果后端（默认 Redis） |
| `MODEL_SAVE_DIR` | 模型文件保存目录 |
| `DEVICE` | 训练设备 `cuda` / `cpu` |
| `FETCH_TIMEOUT` | 抓取脚本超时（秒，默认 120） |
| `BACKTEST_PERIODS` | 回测滑动窗口期数（默认 30） |
| `ENSEMBLE_TOP_K` | 集成融合取榜单前 K 个模型（默认 5） |
| `AGENT_MODEL_TOP_K` | 智能选模返回前 K 个（默认 5） |
| `MODEL_KEEP_LATEST` / `MODEL_KEEP_TOP_SCORED` | 磁盘清理保留数量 |
| `LOTTERY_HOLIDAYS` | 非发布日期（逗号分隔 ISO 日期） |
| `CORS_ORIGINS` | 允许的跨域来源 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | Agent 大模型配置 |
| `EMBEDDING_MODEL_NAME` / `RAG_TOP_K` / `RAG_ENABLED` | RAG 嵌入模型与检索配置（默认关闭） |

## 🤖 AI Agent 机制

- **超参推荐**：调用 DeepSeek LLM（system prompt 限定输出 JSON），失败或 key 无效时**熔断**并回退本地经验超参（epochs=200, bs=128, seq=50, lr=5e-5）
- **RAG 检索**（`RAG_ENABLED=true` 时启用）：用 `SentenceTransformer(all-MiniLM-L6-v2)` 对历史训练任务批量编码，按余弦相似度取 Top-K 相似任务作为 LLM 上下文（首次加载约 10s）
- **模型推荐**：优先按 `model_score.hit_total` 取 Top-K（自我学习反馈），无评分时回退到推断质量评分排序
- 嵌入模型强制离线模式（`HF_HUB_OFFLINE=1`），未缓存时不联网

## 📖 自我学习闭环使用

1. **批量训练**：运行 `batch_train_seqlen.py`，持续产出不同超参的模型
2. **一键智能推断**：推断页点「🚀 一键智能推断」（**仅作算法效果展示，严禁用于商业或决策用途**），自动完成：
   - 后台提交回测（Celery 异步评分，不阻塞）
   - Agent 智能选模 → 批量并行推断（百量级模型秒级）
   - 按回测表现加权融合 Top-5 生成推断号码（首次运行自动等回测出分）
   - 单步操作（Agent 选模 / 单模型推断 / 集成 / 回测 / 清选）收在「更多操作」下拉中
3. **统计图表**：数据管理页「📈 走势图」Tab，查看频率/间隔/和值跨度分布
4. **编号核对**：新批次数据导入后在「吻合度分析」页选择历史批次，逐条核对模型输出与实际数据的吻合度与规则匹配等级

> 回测样本量随数据积累动态增长，榜单自适应更新——这是"自我学习"的核心：模型吻合度反馈驱动模型选择。
>
> 注意：回测/训练是 Celery 异步任务，必须启动 Worker（`celery -A app.core.celery_app worker --pool=threads`），否则任务一直 pending，集成会因无评分等待至超时。

---

## 📄 许可证

本项目采用 [MIT](LICENSE) 许可证，详情见 LICENSE 文件。

Copyright (c) 2026 [ai-zxl](https://gitee.com/ai-zxl)

---

## 🤝 贡献指南

欢迎 Issue 和 Pull Request！请按以下流程参与贡献：

1. **Fork** 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'feat: add your feature'`（遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范）
4. 推送分支：`git push origin feature/your-feature`
5. 提交 **Pull Request**

### 代码规范

- **Python**：遵循 [PEP 8](https://peps.python.org/pep-0008/)，类型注解使用 `typing`
- **Vue / JavaScript**：遵循 [Vue.js 风格指南](https://vuejs.org/style-guide/)
- **SQL / ORM**：字段命名统一使用蛇形命名，新增列必须同步 `app/core/migrations.py` 与 `sql/open-lottery.sql`
- **提交信息**：格式 `<type>(<scope>): <subject>`，常见 type 包括 `feat`、`fix`、`docs`、`refactor`、`test`

---

## 📮 联系方式