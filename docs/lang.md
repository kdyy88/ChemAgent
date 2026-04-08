## ✅ 交付物总览

### 1. 📦 依赖安装
`react-i18next` + `i18next` + `i18next-resources-to-backend` + `i18next-browser-languagedetector`

### 2. 🌐 翻译文件（按需加载）
```
public/locales/
├── zh/ & en/
│   ├── common.json    — 通用 UI 文本
│   ├── chemistry.json — RDKit/OpenBabel 专业术语表（命名空间隔离）
│   └── agent.json     — Node 标签、Tool 标签、状态文案、错误信息
```

### 3. ⚙️ 共享 i18n 配置层 (`lib/i18n/`)
| 文件 | 作用 |
|------|------|
| `config.ts` | 共享常量 (`SUPPORTED_LOCALES`, `LOCALE_COOKIE`, 路径解析) |
| `types.ts` | **TS 类型增强** — `t('chemistry:molecule_weight')` 有完整补全 |
| `server.ts` | Server Components 用 — `await getI18n(lang)` 隔离实例，SSR 安全 |
| `client.ts` | Client 单例 — `LanguageDetector` 按 cookie → navigator → htmlTag 检测 |

### 4. 🚦 Next.js 15 Middleware (`middleware.ts`)
- 解析 `Accept-Language` 头，检测 cookie，按优先级确定 locale
- 未携带 locale 前缀的 URL 自动 **307 重定向** → `/zh/…` 或 `/en/…`
- 每次响应刷新 `NEXT_LOCALE` cookie（1 年有效期）

### 5. 🗂️ `app/[lang]/` 路由结构
- `layout.tsx` — Server Component，读取 `params.lang`，注入 `<I18nProvider locale>`，设置 `<html lang>`
- `page.tsx` / `workflow/page.tsx` — 薄包装，复用原有页面组件

### 6. 🔴 SSE 实时翻译拦截器 (`lib/i18n/sse-interceptor.ts`)
```typescript
// fetchEventSource 回调中，agent 事件实时映射到用户语言
translateNodeLabel('chem_agent')    // zh: "🧠 智能体推理中…"  en: "🧠 Agent reasoning…"
translateToolLabel('validate_smiles') // zh: "校验 SMILES"  en: "Validate SMILES"
translateStatusLabel('task_running', { id: 3 }) // "📋 Executing task 3"
translateReasoningText('复杂度判断完成。') // en: "Complexity assessment complete."
```

### 7. 🗃️ Zustand i18nStore (`store/i18nStore.ts`)
- `persist` 中间件将 `locale` 写入 `localStorage`
- `setLocale(locale)` 同时调用 `i18next.changeLanguage()` + `window.history.pushState` 跳转到新 locale URL
- 与 i18next 状态**双向同步**

### 8. 🔄 sseStore + sse-client 更新
- 所有硬编码中文字符串（`'🛠️ 工具执行中…'`、`'❌ 连接中断:'` 等）替换为拦截器调用
- 后端推回的 `_NODE_REASONING_MESSAGES` 字符串通过 `ZH_REASONING_MAP` 映射到目标语言


**是的，语言切换功能与业务逻辑完全解耦，随时可以弃用。** 具体来说：

| 组件 | 作用 | 弃用方式 |
|---|---|---|
| `components/ui/LanguageSwitcher.tsx` | UI 下拉菜单 | 从 `app/page.tsx` 删除 `<LanguageSwitcher />` |
| `store/i18nStore.ts` | 语言偏好持久化 | 不影响其他 store，可直接删除 |
| `middleware.ts` | URL 路由重定向 | 删除整个文件，或将 `app/[lang]/` 改回 `app/` |
| `lib/i18n/` | 翻译配置与 SSE 拦截器 | `sse-interceptor.ts` 依赖 i18next，但其余业务组件不依赖它 |

最简弃用方式：删除 `<LanguageSwitcher />`，将 `DEFAULT_LOCALE` 固定为 `'zh'`，删除 `middleware.ts`，`app/[lang]/` 目录改回 `app/`。所有业务逻辑（SSE、Zustand stores、API 调用）**不依赖** i18n 基础设施。

Made changes.