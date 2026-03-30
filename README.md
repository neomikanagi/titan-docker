# Titan Guardian（Docker 金融脚本环境）

这是一套**现成的容器环境**：里面装好 Python 3.12、你的依赖包、以及**每周一早上自动跑一次** `main.py` 的定时任务。你只需要把业务逻辑写进 `main.py`（或自己加模块再导入），在本地或服务器上用 Docker **构建镜像 → 运行容器**即可。

---

## 技术选型（用大白话说明）

| 项目 | 选择 | 为什么 |
|------|------|--------|
| **基础系统** | 官方镜像 `python:3.12-slim-bookworm` | 基于 Debian Bookworm，体积比「完整 Python 镜像」小很多，又比 Alpine 更适合装 **pandas / numpy**（预编译包更省心）。 |
| **Python 版本** | 3.12 | 与你要求一致，且长期支持较好。 |
| **装依赖的方式** | [uv](https://github.com/astral-sh/uv) | 比传统 `pip install` 快很多；Docker 里一层缓存装好依赖，改代码时不必反复重装包。 |
| **依赖声明** | `pyproject.toml` + `uv.lock` | `pyproject.toml` 写「要哪些包」；`uv.lock` 锁死具体版本，**本地和 CI 构建结果一致**。GitHub Actions 里每周会执行 `uv lock --upgrade`，再构建镜像，相当于**每周自动尝试用较新的兼容版本**。 |
| **定时任务** | `cron` | Linux 上最常见、够用的计划任务；规则写在 `docker/crontab` 里。 |

默认时区为 **Asia/Shanghai**，定时为 **每周一 08:00** 执行（可按下面说明修改）。

---

## 开始前：你需要装什么？

1. **Docker**（用来构建和运行容器）
   - macOS / Windows：一般安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。
   - 装好后在终端执行 `docker --version`，能显示版本号即可。

2. **（可选）本机开发用 uv**  
   若你想在**不启动容器**的情况下在本机装依赖、跑脚本，可安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。不装也不影响「只用 Docker」的流程。

---

## 在本地「构建」镜像（build）

在终端里进入本项目目录（里面有 `Dockerfile` 的那一层），执行：

```bash
docker build -t titan-guardian:local .
```

含义简要说明：

- `docker build`：根据当前目录下的 `Dockerfile` 做镜像。
- `-t titan-guardian:local`：给镜像起个名字和标签，方便下面运行；名字可以改成你喜欢的。
- `.`：表示「用当前目录作为构建上下文」（会把需要的文件打包进构建过程）。

第一次构建会下载基础镜像和依赖，可能稍慢；以后再构建，若只改了 `main.py`，会快很多。

---

## 在本地「运行」容器（run）

构建成功后，执行：

```bash
docker run --name titan-guardian -d titan-guardian:local
```

含义简要说明：

- `docker run`：用镜像启动一个容器。
- `--name titan-guardian`：容器名字叫 `titan-guardian`，方便以后管理。
- `-d`：**后台运行**（守护进程），这样终端不会被占住。
- `titan-guardian:local`：使用你刚才构建的镜像。

容器里会启动 **cron**，并按 `docker/crontab` 里的规则在**每周一 08:00（上海时区）**执行 `/app/main.py`。

### 看容器是否在跑

```bash
docker ps
```

列表里能看到 `titan-guardian` 且状态为 `Up` 即表示在运行。

### 看定时任务或脚本的输出（日志）

```bash
docker logs -f titan-guardian
```

`-f` 会持续跟着新日志输出；按 `Ctrl+C` 只退出日志查看，**不会**停掉容器。

### 想立刻手动跑一次 `main.py`（不等周一）

```bash
docker exec titan-guardian /app/.venv/bin/python /app/main.py
```

你应该能看到终端打印：`Titan Guardian Running...`

### 停止 / 删除容器（需要时）

```bash
docker stop titan-guardian
docker rm titan-guardian
```

---

## 改定时时间（cron）

编辑本仓库里的 **`docker/crontab`**。  
里面一行以 `0 8 * * 1` 开头的那段表示：**每周一 8 点 0 分**（配合容器内的 `TZ=Asia/Shanghai`）。

[cron 格式](https://zh.wikipedia.org/wiki/Cron) 从左到右大致是：分、时、日、月、星期。改完后需要**重新构建镜像并重新运行容器**才会生效。

---

## 依赖与业务代码放哪里？

- **加依赖 / 改版本**：编辑 `pyproject.toml`，然后在项目目录执行：

  ```bash
  uv lock
  ```

  会更新 `uv.lock`。再重新 `docker build`。

- **写你的逻辑**：主要改 **`main.py`**（或新建 `.py` 文件并在 `main.py` 里导入）。

- **敏感信息（API Key 等）**：用环境变量，本地可配合 `.env`（勿提交到 Git）；运行时：

  ```bash
  docker run --name titan-guardian -d --env-file .env titan-guardian:local
  ```

  需在代码里用 `python-dotenv` 或读取系统环境变量（按你的习惯二选一即可）。

---

## GitHub Actions：每周构建并推送到 GHCR

仓库里有 **`.github/workflows/docker-publish.yml`**，会：

1. **每周日（UTC 时间，见 workflow 内注释）**自动运行；
2. 执行 `uv lock --upgrade` 刷新当次构建所用的锁文件；
3. 构建 Docker 镜像并推送到 **GitHub Packages（GHCR）**。

### 你需要做的

1. 把本项目推送到 **GitHub 仓库**（公开或私有均可，按你账号权限）。
2. 在仓库 **Settings → Actions → General** 里，确认允许 Actions（默认一般已开）。
3. 推送后可在 **Actions** 页看到工作流；成功后到 **Packages**（或与仓库关联的容器包）里查看镜像。

### 拉取 GitHub 上构建好的镜像（示例）

把下面占位符换成你的 **GitHub 用户名** 和 **仓库名**（**小写**更省事）：

```bash
docker login ghcr.io -u <你的GitHub用户名>
# 密码处粘贴 Personal Access Token（需要 read:packages；若私有镜像可能还要相应权限）
docker pull ghcr.io/<用户名>/<仓库名>:latest
docker run --name titan-guardian -d ghcr.io/<用户名>/<仓库名>:latest
```

首次从 GHCR 拉取私有镜像时，需要 [配置登录](https://docs.github.com/packages/working-with-a-github-packages-registry/working-with-the-container-registry)。

---

## 常见问题

**Q：构建报错找不到 `uv.lock`？**  
A：在项目根目录执行 `uv lock` 生成锁文件后再 `docker build`。

**Q：想用美国盘前时间而不是上海时间？**  
A：改 `Dockerfile` 里的 `TZ` 环境变量，并同步理解 `docker/crontab` 里对应的是哪个时区。

**Q：容器一启动就退出了？**  
A：本项目的 `CMD` 会启动 `cron` 并 `tail -f` 保持前台进程；若你改过 `Dockerfile` 的 `CMD`，请保证有**长期运行的进程**，否则容器会退出。

---

如有某一步在你电脑上报错，把**完整报错原文**贴出来，便于对照环境排查。
