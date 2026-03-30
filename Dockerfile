FROM python:3.12-slim-bookworm

# 保持 Python 输出不缓冲，且不生成 pyc 文件，设定默认时区
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tokyo

# 官方 uv 二进制，零配置极速安装
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先只拷贝依赖描述，利用 Docker 层缓存：改业务代码不触发重装依赖
COPY pyproject.toml uv.lock ./

# 用 uv 创建虚拟环境并安装依赖（--frozen 与 uv.lock 严格一致）
RUN uv sync --frozen --no-dev

# 拷贝占位用的空壳 main.py（真实的脚本会在 Unraid 里通过 -v 挂载覆盖）
COPY main.py ./main.py

# 终极奥义：启动即运行，运行完即销毁
CMD ["/app/.venv/bin/python", "/app/main.py"]
