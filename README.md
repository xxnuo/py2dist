# PyProtector

PyProtector 是一个使用 Cython 将 Python 源代码编译为二进制扩展模块（.so/.pyd）的工具，用于保护源代码。

## 功能

- 将单个 .py 文件或整个目录编译为二进制文件
- 保持目录结构
- 支持排除指定文件或目录
- 自动检测并使用 ccache 加速编译
- 提供 CLI 和 Python API

## 安装

```bash
pip install pyprotector
```

## 使用方法

### 命令行界面 (CLI)

编译单个文件：
```bash
pyprotector -f myscript.py
```

编译整个目录：
```bash
pyprotector -d myproject -o dist
```

参数说明：
- `-f, --file`: 指定要编译的单个 .py 文件
- `-d, --directory`: 指定要编译的目录
- `-o, --output`: 输出目录 (默认为 `dist`)
- `-m, --maintain`: 排除的文件或目录 (逗号分隔)
- `-x, --nthread`: 编译线程数 (默认为 1)
- `-q, --quiet`: 安静模式
- `-r, --release`: 发布模式 (清理临时构建文件)
- `-c, --ccache`: 使用 ccache (默认自动检测，也可指定路径)

### Python API

```python
from pyprotector import compile_file, compile_dir

# 编译单个文件
compile_file("myscript.py", output_dir="dist")

# 编译目录
compile_dir(
    "myproject",
    output_dir="dist",
    exclude=["tests", "setup.py"],
    nthread=4
)
```

## ⚠️ 重要提示：Python 版本一致性

编译生成的二进制扩展模块（.so/.pyd）与特定的 Python 版本绑定。**您必须确保编译时使用的 Python 版本与运行时使用的 Python 版本完全一致**（包括次要版本号，例如 3.10 和 3.11 是不兼容的）。

如果版本不匹配，导入模块时可能会遇到如下错误：
`ImportError: ... undefined symbol: _PyThreadState_UncheckedGet`
或者
`ModuleNotFoundError: No module named ...`


## 开发与发布

### 本地开发

安装依赖：
```bash
make install
```

运行测试：
```bash
make test
```

构建包：
```bash
make build
```

### 发布新版本

本项目使用 GitHub Actions 自动发布到 PyPI。

1. 确保已配置 PyPI 的 Trusted Publishing 或 Secrets。
2. 使用 `make release` 命令更新版本号并推送 tag：

```bash
make release v=0.1.1
```

这将自动更新 `pyproject.toml` 和 `__init__.py` 中的版本号，提交更改，打上 `v0.1.1` 的 tag，并推送到 GitHub。GitHub Actions 检测到新 tag 后会自动构建并发布到 PyPI。
