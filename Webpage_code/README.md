# Webpage_code

基于仓库中的设计导出图 `front/src/主线分析.png` 实现的 React + TypeScript 页面。

> 说明：当前仓库不支持提交二进制文件，因此未在 `Webpage_code` 中复制设计原图，请直接使用仓库内现有路径 `front/src/主线分析.png` 作为视觉对照。

## 启动

```bash
cd Webpage_code
npm install
npm run dev
```

默认访问：`http://localhost:5173`

## 后端接口对接

- 页面会优先请求后端接口：`GET http://127.0.0.1:8092/api/news/latest?limit=100`
- 可通过环境变量覆盖 API 地址：

```bash
VITE_API_BASE_URL=http://你的后端地址 npm run dev
```

- 如果接口不可用，页面会自动回退到设计稿示例数据，保证 UI 可预览。

## 已实现交互

- 顶部指数概览区（3 指数卡片）
- 左侧资讯子界面（情绪卡、板块过滤、资讯列表）
- 主线分类切换（全部 / 偏好 / 热度）
- 板块关键字搜索
- 排序切换（默认 / 综合分 / 资讯数 / 最新时间）
- 场景态切换（实时数据 / 加载态 / 空态 / 错误态）
- 单卡片展开/收起（查看附加说明）
- 卡片激活高亮态
- 手动刷新接口数据
- 接口加载态 / 异常回退态提示

## 构建

```bash
npm run build
npm run preview
```
