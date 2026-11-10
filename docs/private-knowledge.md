# 用户私有知识库设计与使用

## 选型与边界

已确认首期：SQLite 元数据/FTS5、可选本地或外部 Embedding、带原文证据与时间的关系表。与对话记忆分库，仅复用 X-Memory-Key 身份。保持单机 loopback 服务边界；本地操作者拥有磁盘权限，不是互联网多租户托管服务。

向量擅长同义语义召回，但依赖模型且容易漏掉代码、精确数字。关键词/FTS 适合股票代码、财务指标和原文定位，中文单字/双字分词不依赖额外搜索服务。图谱适合供应链和事件关联，但自动抽取易产生无依据的边，需要来源和有效期。推荐将关键词与模型向量按排名融合，再做有限跳数关系扩展。原始资料、日期、权限先过滤，不能让模型猜权限。

首期用 SQLite 关系表查询一至两跳，无独立图数据库成本，文件与 SQLite 均可私有化部署；向量用精确余弦扫描，适合本机中小规模资料。数据增加时先测延迟，再引入本地向量扩展或独立向量服务；只有复杂多跳遍历与规模确有需求才考虑图数据库。届时保留 owner、证据定位和时态条件，不以迁移替代授权。

## 数据及任务

接收→解析→清洗→结构化/切分→向量→索引。清洗 Agent 是独立命令 worker，持久步骤检查点和失败原因，不由分析动态委派触发。原文件按用户和版本 ID 加密且不可变保存，内容摘要用于去重；更新生成新版本，准备好后切换活动版本；失败继续使用旧版本。重复内容与相同元数据不重复导入。删除清理该用户的原文件、片段、关系和全部索引代；查询无跨请求缓存。

数字 PDF 使用 pypdf；DOCX 使用标准库 OOXML；UTF-8 TXT/MD/CSV/JSON 使用标准库；XLSX 使用 openpyxl。旧 .doc/.xls 不支持。扫描件需 OCR，首期不执行；复杂表格、合并单元格、公式缓存缺失等标记复核。清洗不推断缺失值，不自动换算金额单位。保留原始文本与清洗文本、页/段落/工作表/行单元格定位；表格行重复列名，保留周期与单位。关系仅从带 subject/predicate/object 的结构化行导入，不承诺从任意文章抽取全部实体。

## Embedding 与索引

OpenAI 兼容 /embeddings 与 Ollama /api/embed 通过统一适配器调用；Ollama 使用 truncate=false，避免静默丢失输入。模型名、用户声明的版本、实际维度和配置指纹与索引代绑定；同名模型服务端若悄然更新权重无法自动识别，需主动更新版本并重建。API key 加密保存，不在响应中回显。

配置查询接口返回外部服务完整目的地址；本轮按要求不改前端，未明确允许外发则不发送资料或查询。索引构建期间旧索引继续用旧配置；完整生成后在事务中切换。中途失败不激活部分索引。构建、更新与删除通过数据修订号检测并发，避免复活已删除文件。

## 引用与时间

文档日期、可用时间和关系有效期分别记录。查询 as_of 排除未来资料；日期缺失显式警告。回答使用可定位的引用片段，资料永远是待分析数据，不执行其中指令。来源冲突需要保留各版本与日期，不把未知描述成事实。过期与证据不足给出警告；关系扩展只使用当前用户有权限的活动版本。

## 官方接口依据

- [SQLite FTS5](https://www.sqlite.org/fts5.html)：全文检索及分词机制（2026-11-07 经 gstack browse 核实）。
- [Ollama embed](https://docs.ollama.com/api/embed)：批量 input、embeddings 返回数组及 truncate 参数（2026-11-07 经 gstack browse 核实）。

## 启动与独立清洗 Agent

```powershell
uv sync --all-extras
# console 与 worker 使用相同 workspace 和进程环境中的 STOCK_PREDICT_MAILER_MASTER_KEY。
# 主密钥沿用现有控制台设置；不要生成新密钥覆盖已有工作区的密钥。
uv run stock-predict-mailer --config config/local.toml console
# 另开终端运行；持续轮询仅处理上传任务，与动态分析子 Agent 预算无关。
uv run stock-predict-mailer --config config/local.toml knowledge-worker --poll 2
# 或一次处理当前队列，完成后退出：
uv run stock-predict-mailer --config config/local.toml knowledge-worker --once
```

只需知识库依赖时可用 `uv sync --extra knowledge --extra dev`；研究功能还需对应 research/trees extra。上传不会自动启动 worker。独立进程持有自己的 OS 锁，避免双 worker 恢复对方的运行任务；进程中断后再次启动将 processing 标为失败，需显式 retry。`--once` 有失败任务返回 2，否则返回 0；`--poll` 为 .1–60 秒。每次解析完成保存 parsed 检查点，清洗完成保存 chunked 检查点，重试从其后继续。向量/索引发布事务失败回滚，不暴露半成品。

资料保存在 `<workspace>/private-knowledge/knowledge.sqlite3` 及用户子目录；与 control.sqlite3 的对话记忆不同。原文件和 API key 用现有主密钥加密，片段/FTS/元数据为本机明文索引，需依靠工作区磁盘权限保护。备份时须保留原文件、索引、control.sqlite3 的用户身份以及外部保存的原主密钥。逻辑删除会移除当前索引记录和加密文件，不宣称磁盘取证级安全擦除。

## HTTP 接口

先从同源本机控制台建立 session，读取 `GET /api/session` 的 csrf_token。创建身份：`POST /api/memory/access`（JSON `{}`），妥善保存返回 key。所有知识库接口都必须携带 `X-Memory-Key`；所有写操作还须携带 `X-CSRF-Token` 和同源 session cookie。不得在 query URL 中传访问密钥。以下路径均以 `/api/knowledge` 为前缀。

- `POST /documents`：`{"filename":"report.csv","data":"<base64>","logical":"财报","metadata":{...}}`。原文件上限 10 MiB，JSON 请求上限 15 MiB；响应 202 只表示 pending。logical 省略时用文件名；更新时保持 logical，上传新字节或新元数据。原格式 `.doc/.xls` 不支持。
- `GET /documents`：本用户所有版本、active 标记、上传时间、处理 status/step/error/error_message、warnings 和 needs_review。
- `GET /documents/{id}`：清洗前 original 摘录、清洗后 text、原始 fields、normalized_fields、结构标题与定位、实体和代码。长文本按结构分界与有限重叠切分，定位的 extracted_text_offset 是解析文本内字符位置，不是 PDF 二进制偏移。
- `GET /documents/{id}/original`：返回 filename 和 base64 原文件，供 PDF 页、工作表、重要数值对照。原件不能执行为工具。
- `POST /documents/{id}/retry`：仅允许失败任务重排队；原文件不变，需更换文件则上传新版本。
- `DELETE /documents/{id}`：删除此版本的原文件、片段、全部索引代向量、关系和 FTS。无跨请求检索缓存；删除活动版本不自动复活旧版本。旧的独立分析报告属于历史输出，需操作者另行管理，不会因资料删除被重写。
- `GET/PUT /config`：查询/保存用户自己的 Embedding 配置。响应只含 has_secret；api_key 不回显。变更服务地址不自动沿用旧服务的认证 key。
- `POST /test`：只发送两条固定测试文本，验证向量数量、维度、有限数值与非零向量。provider=none 返回 lexical_only。
- `POST /rebuild`：同步构建新索引代，其他请求仍可查询旧代；完成后事务切换。资料或配置在重建期间变化会报 INDEX_CHANGED，需重新调用。失败重试不会覆盖旧代。
- `GET /indexes`：查询各代状态、失败码、模型、声明版本、维度与不含凭据的配置指纹。
- `POST /search`：`{"query":"营业收入","as_of":"2026-11-07","start_date":"2026-01-01","stock_code":"600000.SH","entity":"甲公司","limit":8}`，可选条件按 AND 组合，limit 1–20。文档日期、资料可用时间及记录的 data_date/date/日期/数据日期会按截止时间过滤；未知文档日期标记警告。结构化日期支持 YYYY-MM-DD 和 YYYY/MM/DD，原字段保留。代码按 A 股 SH/SZ/BJ 六位规则规范；不宣称其他市场代码自动识别。
- `POST /answer`：相同查询参数，返回摘录、条件性推断、逐条 citation_id、来源日期、定位、冲突候选、过期/不足说明。使用确定性有界规则，不需要配置聊天模型。
- `GET /citations/{document_id}:{ordinal}`：按当前用户权限定位片段和源版本；退休版本仍可对照，已删除则不存在。

metadata 支持 source、document_date、available_date、valid_to、companies、industries、topics、stock_codes。默认 available_date 为上传当天；历史回放需填写真实可用日期，不能把文件里出现的未来时间当作当时已知。document_date 缺失会提示未知，不自动从文件名猜测。单位保留在字段名与原始文本，不做金额换算；JSON 数字按词法字符串保留，避免小数精度在清洗时变化。

## Embedding 配置示例

Ollama（模型须已在服务端准备好，本工具不自动下载）：

```json
{"provider":"ollama","base_url":"http://127.0.0.1:11434","model":"embeddinggemma","version":"user-declared-v1","timeout_seconds":30,"allow_external":false}
```

OpenAI 兼容服务（base_url 包含服务实际使用的 /v1 前缀；不是完整 embeddings 路径）：

```json
{"provider":"openai_compatible","base_url":"https://embedding.example.com/v1","model":"your-embedding-model","version":"user-declared-v1","timeout_seconds":30,"allow_external":true}
```

通过 PUT /config 的 api_key 字段单独传凭据，不把真实 key 写入仓库。远程地址要求 HTTPS 且显式 allow_external=true；本地 loopback 可用 HTTP。HTTP 重定向禁止，避免认证信息转发给其他目的地。配置保存后先 POST /test，再 POST /rebuild。旧索引继续绑定旧配置；撤销外发许可或改换远程目的地后，旧远程索引查询降级为关键词检索，不继续向原服务发查询。provider=none + rebuild 可切回纯本地词法检索。

## 供应链验收资料

先将以下 JSON 保存为本机文件，经 POST /documents 上传；metadata 可设 document_date/available_date=2026-10-01，logical=供应链。

```json
[
  {"subject":"甲公司","predicate":"供应商","object":"乙公司","valid_from":"2026-01-01","valid_to":"2026-12-31"},
  {"subject":"乙公司","predicate":"所属行业","object":"半导体","valid_from":"2025-01-01"},
  {"subject":"甲公司","predicate":"供应商","object":"旧供应商","valid_to":"2025-12-31"}
]
```

再上传 TXT：`乙公司发生停产事件，半导体交期可能延长，影响规模未披露。`，填写来源和可用日期。运行 worker 后调用：

```json
{"query":"甲公司的供应链风险","entity":"甲公司","as_of":"2026-11-01"}
```

预期回答保留供应商关系、行业和事件的原始 JSON Pointer/行号，排除旧供应商的过期关系；若有效且日期明确的供应商关系和停产事件同时出现，产生带两条原文引用的条件性“交付连续性风险”推断，并声明采购占比、替代能力、事件范围不足以量化。缺少这些条件时只给摘录和证据不足说明，不虚构因果结论。

## 分析任务接入

现有 POST /api/tasks 的私有 conversation_id 任务可增加 knowledge_query 字符串，返回结果的 knowledge 附录是同一私有检索接口生成的证据回答。默认 knowledge_to_model=false，不把资料内容发送给聊天模型；显式设 true 才以 source_material/untrusted_source_material 字段发送给已配置的主模型。外部聊天模型可能收到原文，须由操作者在任务级决定。资料不作为对话记忆条目自动入库，也不会获得工具或邮件权限。原有股票预测结论代码和证据校验保持约束，不允许模型借资料任意输出未校验的因果结论。

## 测试与未验证范围

`uv run python -m unittest discover -s tests -p test_private_knowledge.py -q` 使用临时工作区、合成七种格式资料和本地 HTTP 模拟服务，覆盖 Ollama 与 OpenAI 兼容协议、失败切换、删除/更新、权限、记录日期、数值单位、清洗检查点、引用及供应链条件性推断。真实外部 Embedding 服务、真实 Ollama 模型效果、超大资料库性能和复杂 PDF/OCR 准确率未验证。前端按本轮要求未实现。


## 可选语义清洗模型

独立清洗聊天模型及证据复核已增加，默认关闭。启用后模型处理的文档先进入 review，经私有审批后才发布；与 Embedding 配置独立。配置、接口和限制见 [语义清洗 Agent](cleaning-agent.md)。


## 2026-11-08 正确性与历史语义修正
重复JSON键（包括嵌套）与重复/空DOCX表头、DOCX列数不一致拒绝为 REVIEW_REQUIRED；原件仍保留待修正。正文裸六位金额不推断证券代码，仅带市场后缀或明确证券字段/显式metadata可识别。
as_of按 logical 选择截止日已可用、已发布版本（available_date、uploaded、id顺序），不是还原当时系统是否已经录入的双时态快照。仅对当前仍存在活动授权版本的logical回放；删除当前活动版本不复活旧版。历史向量不保证有当前索引覆盖，仍可词法检索。
DELETE先将版本标为 deleting 并停止检索，原件unlink成功后清理数据库。Windows占用失败返回 DELETE_PENDING/retryable=true，记录与原件定位保留，可再次DELETE；不声称物理擦除。
