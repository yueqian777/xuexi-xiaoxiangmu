# INTP Study Manager Desktop

Tauri 只作为桌面壳加载 `frontend/`，业务逻辑、认证、AI Provider、PPT/PDF 解析和数据库访问都保留在 Spring Boot 后端。

开发模式：

```bash
cd desktop/src-tauri
cargo tauri dev
```

前端开发服务默认代理 `/api` 到 `http://127.0.0.1:8080`。
