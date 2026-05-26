# INTP Study Manager Frontend

React + TypeScript + Vite 前端，复刻 Python Streamlit 版本的侧边栏导航、中文字段、学习业务页面和 PPT/PDF 三栏阅读器首版。

## 开发

先启动 Spring Boot 后端：

```bash
cd ../backend
mvn spring-boot:run
```

再启动前端：

```bash
npm install
npm run dev
```

默认地址：`http://127.0.0.1:5173/`，`/api` 会代理到 `http://127.0.0.1:8081`。

## 构建

```bash
npm run build
```

## 桌面壳

Tauri 只加载前端，不承载业务逻辑：

```bash
npm run tauri:dev
```
