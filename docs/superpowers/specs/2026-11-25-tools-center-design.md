# 工具中心设计

## 背景

当前控制台已经提供模型、MCP、工作流和插件能力，但入口分散在设置页、分析工作台和插件弹窗中。用户需要一个接近参考截图的统一工具中心，用于发现、创建和管理这些能力。

本次交付采用新增顶部主导航的方式。现有设置页继续保留，避免改变已有配置入口和 API 契约。

## 目标

- 在顶部主导航增加「工具中心」页面
- 在一个页面内聚合工具、工作流、MCP、插件和本地自定义工具
- 提供三个明确的创建入口
  - 添加 MCP 服务请求
  - 创建自定义工具
  - 添加插件
- 复用已有 MCP、插件和工作流接口
- 保持凭据、CSRF、Host、Origin 和内容安全边界
- 在桌面和窄屏下保持可操作

## 非目标

- 不新增登录、多租户或公网部署能力
- 不改变现有分析任务 API
- 不把自定义工具密钥保存到 localStorage
- 不重写现有工作流画布
- 不删除设置页的模型、MCP、协作或邮件配置

## 信息架构

顶部主导航增加 `data-view="tools"`。页面使用 `data-view-pane="tools"`，与现有 overview、analysis、records、settings 和 memory 视图保持同一切换机制。

工具中心页面包含以下区域。

1. 页面标题、说明、搜索框和标签筛选
2. 四个分类标签
   - 工具
   - 自定义
   - 工作流
   - MCP
3. 三张固定操作卡
   - 添加 MCP 服务请求
   - 创建自定义工具
   - 添加插件
4. 统一资源网格
   - 已配置 MCP 服务
   - 工作流内置工具
   - 已安装插件
   - 浏览器本地自定义工具

分类切换和搜索只过滤工具中心的资源，不改变后端设置页状态。工具中心卡片中的工作流操作打开现有专业工作流画布，内置工具操作调用已有 `DesktopWorkbench.addBuiltinTool`。

## 组件边界

### 工具中心模块

新增 `tools-center.js` 模块，负责页面挂载、资源读取、筛选、卡片渲染和弹窗生命周期。模块复用全局 `api`、`text`、`action` 和 `showView` 函数，不复制已有请求和错误处理逻辑。

模块通过以下读取接口构建视图。

- `GET /api/mcp`
- `GET /api/plugins`
- `GET /api/workflows/catalog`
- `GET /api/settings`

资源加载失败时分别显示对应区域的错误和重试操作。一个区域失败不会阻塞其他区域显示。

### MCP 弹窗

弹窗由工具中心创建并使用真实 `label`。字段分为三部分。

- 基础信息
  - 服务端点 URL
  - 名称
  - 图标选择
  - 服务器标识符
- 认证
  - 动态客户端注册
  - 客户端 ID
  - 客户端密钥
- 请求头和配置
  - 可重复的请求头键值行
  - 请求超时
  - SSE 读取超时

现有 `MCPProfile` 只接受当前后端支持的字段。界面会把认证和配置字段映射到现有 `transport`、`url`、`auth_token`、`timeout_seconds` 和 stdio 配置。后端不支持的客户端注册字段只作为本次请求表单的浏览器状态，不会伪造写入未登记字段。提交调用 `POST /api/mcp`，创建成功后调用统一刷新。

保存按钮在必填字段和 URL 格式通过前禁用。错误使用全局 notice 和弹窗内状态同时反馈。

### 自定义工具弹窗

弹窗字段包括名称、图标、OpenAPI Schema、从 URL 导入、示例选择、标签、鉴权方式、隐私协议和自定义免责声明。Schema 解析在浏览器完成，支持 OpenAPI 3 和 Swagger 2 的基础信息、路径、方法、描述和参数提取。

解析出的工具显示为名称、描述、HTTP 方法和路径的只读表格。保存结果写入浏览器本地工具库，只保存名称、图标、Schema 摘要、工具列表、标签和声明文字。Schema 原文和任何疑似凭据字段都会在写入前过滤或不保存。自定义工具卡片支持编辑、删除和加入工作流。加入工作流时优先调用现有工作流画布的自定义节点入口，若画布不可用则显示可执行提示。

### 插件弹窗

弹窗包含 GitHub 仓库地址、仓库默认分支提示和安装状态。提交调用 `POST /api/plugins/github`，沿用已有插件模块的安装、刷新和错误处理逻辑。插件卡片显示名称、能力、来源、可用状态和移除操作，移除调用已有删除接口。

## 数据流

```text
工具中心打开
  ├─ GET /api/mcp
  ├─ GET /api/plugins
  ├─ GET /api/workflows/catalog
  └─ GET /api/settings

添加 MCP 服务请求
  └─ POST /api/mcp → 刷新 MCP 与工具中心

创建自定义工具
  └─ 浏览器校验 Schema → localStorage 工具库 → 渲染自定义卡片

添加插件
  └─ POST /api/plugins/github → 刷新插件与工具中心
```

自定义工具使用版本化的 localStorage 键 `stock_predict_mailer.tools.center.v1`。写入失败时保留当前内存状态并显示“仅本次打开有效”，不阻塞其他资源。

## 视觉和交互

工具中心使用独立的浅色视觉层，不修改现有全局深色主题。背景使用浅灰，卡片使用白色，主操作使用蓝色，弹窗使用白色圆角面板和遮罩。资源卡片采用四列自适应网格，宽度不足时降为两列和单列。

弹窗在桌面居中显示，在窄屏接近全宽并允许内容滚动，底部操作栏保持可见。关闭方式包括关闭按钮、取消按钮、Esc 和点击遮罩。打开弹窗后焦点进入第一个可编辑字段，关闭后返回触发按钮。

外部文本使用 `textContent` 或 `text` 创建节点，不使用未过滤的 `innerHTML`。长 URL、Schema 和标识符允许换行或在局部区域滚动。

## 错误和权限

- MCP 保存失败时保留表单内容，提示服务端错误码和可执行建议
- MCP 已创建但没有授权工具时，卡片显示“已连接，待授权”
- 插件缺少依赖时显示“缺依赖”，不显示为可用
- GitHub 安装失败时不刷新为成功状态
- Schema 解析失败时显示路径、方法或字段所在位置
- 未配置后端会话时沿用现有 `FORBIDDEN` 处理
- 不自动扩大工具白名单，不自动发送邮件
- 密钥字段使用 password 控件，提交后清空内存输入

## 验收

### 页面行为

- 顶部工具中心导航可打开，刷新和 hash 切换不会破坏现有视图
- 分类、搜索、标签筛选能同时生效
- 空态提供对应的新增操作
- MCP 弹窗的基础信息、认证、请求头和配置标签可以切换
- MCP 创建成功后设置页和工具中心显示同一服务
- 自定义工具 Schema 可以解析成功并显示可用工具
- 自定义工具错误可以定位并且不会写入无效记录
- GitHub 插件创建、刷新和移除状态正确
- 工作流卡片能打开现有专业工作流画布

### 安全和兼容

- 现有 Host、Origin、CSRF 和 CSP 校验不变
- 凭据不写入 URL、localStorage、console 或错误文本
- 外部名称、描述、URL 和 Schema 不执行脚本
- `scripts/build_console.py --check` 通过
- `scripts/build_console.py --check-budget` 通过
- 现有控制台回归测试通过

## 交付文件

- `src/stock_predict_mailer/control/web/index.html`
- `src/stock_predict_mailer/control/web/modules/tools-center.js`
- `src/stock_predict_mailer/control/web/style.css`
- `src/stock_predict_mailer/control/web/memory.js`
- `scripts/build_console.py` 仅在模块注册需要时调整

