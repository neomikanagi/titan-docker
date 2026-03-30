# 选型说明：python:3.12-slim-bookworm 是官方「瘦」镜像，体积远小于完整版，
# 且对 pandas / numpy 的预编译 wheel 兼容性好（比 Alpine 省心）。
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# cron：定时任务；tzdata：时区；curl：可选健康检查或调试
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 官方 uv 二进制，零配置加速 pip 兼容安装
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先只拷贝依赖描述，利用 Docker 层缓存：改业务代码不触发重装依赖
COPY pyproject.toml uv.lock ./

# 用 uv 创建虚拟环境并安装依赖（--frozen 与 uv.lock 严格一致，可复现构建）
RUN uv sync --frozen --no-dev

COPY main.py ./main.py

COPY docker/crontab /etc/cron.d/titan-guardian
RUN chmod 0644 /etc/cron.d/titan-guardian

# cron 读取 /etc/cron.d/ 下文件；前台保持进程不退出
CMD ["sh", "-c", "cron && exec tail -f /dev/null"]
