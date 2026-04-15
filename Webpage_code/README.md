# Webpage_code - A股资讯分析前端

基于 `webpage`（Figma Make 导出工程）重构出的可运行 React + TypeScript 前端项目。

## 启动方式

```bash
cd Webpage_code
npm install
npm run dev
```

默认 Vite 本地地址：`http://localhost:5173`

## 构建

```bash
npm run build
```

## 目录结构

- `src/components`：页面组件与业务模块（资讯卡片、板块趋势、弹窗等）
- `src/pages`：页面级容器（DashboardPage）
- `src/assets`：静态资源目录
- `src/styles`：全局样式与主题样式
- `src/App.tsx`：应用入口组件
- `src/main.tsx`：挂载入口
