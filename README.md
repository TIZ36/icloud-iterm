# iCloud CLI Tool

命令行工具，用于在 Linux/macOS 终端环境下同步 iCloud Drive 文件。个人使用，单向同步，信任本地修改。

## 特性

- 🔐 支持 Apple ID 登录（包括双因素认证）
- 🌏 自动检测国际/中国大陆账号
- 📁 浏览和下载 iCloud Drive 文件
- ⬆️ 上传本地修改到 iCloud
- ⚡ 并发下载，速度更快
- 🔒 密码安全存储在系统 keyring

## 安装

### macOS / Linux（推荐）

```bash
# 克隆项目
git clone <repo-url>
cd icloud-iterm

# 一键安装（自动配置环境和全局命令）
./install.sh
```

安装完成后，`icloud` 命令即可全局使用。

### Windows

```bash
# 克隆项目
git clone <repo-url>
cd icloud-iterm

# 使用 pip 安装
python -m venv venv
venv\Scripts\activate
pip install -e .
```

## 快速开始

```bash
# 1. 登录 iCloud
icloud login -u your@icloud.com

# 2. 查看 iCloud Drive 文件
icloud list                    # 列出根目录
icloud list Documents          # 列出 Documents 文件夹

# 3. 下载文件到本地
icloud sync -f Documents       # 同步 Documents 文件夹

# 4. 编辑后上传
icloud submit file.txt         # 上传修改到 iCloud
```

## 命令详解

### 登录/登出

```bash
# 登录（支持双因素认证）
icloud login                       # 交互式登录
icloud login -u your@icloud.com    # 指定用户名

# 登出
icloud logout
```

### 浏览文件

```bash
# 列出文件
icloud list                    # 列出根目录
icloud list Documents          # 列出 Documents 文件夹
icloud list Documents -r       # 递归列出所有文件

# 查看状态
icloud info                    # 显示当前状态
```

### 下载文件

```bash
# 同步整个文件夹
icloud sync                        # 同步 Documents（默认）
icloud sync -f Documents           # 同步 Documents
icloud sync -f "Documents/Work"    # 同步子文件夹

# 同步选项
icloud sync -w 16                  # 使用 16 个并发线程
icloud sync -d 2                   # 只同步 2 层深度
icloud sync --no-exclude           # 不跳过 .git 等文件夹

# 下载单个文件
icloud download Documents/file.txt              # 下载到当前目录
icloud download Documents/file.txt ./local.txt  # 指定本地路径
```

### 上传文件

```bash
# 直接上传
icloud submit file.txt             # 上传单个文件
icloud submit *.py                 # 上传多个文件
icloud submit -a                   # 上传所有已标记的文件
icloud submit file.txt -f Documents  # 指定远程文件夹

# 先标记再上传（可选）
icloud add file.txt                # 标记文件
icloud submit -a                   # 上传所有标记的文件

# 取消标记
icloud revert file.txt
```

### 自动检测变更

```bash
# 扫描本地变更，自动标记修改过的文件
icloud reconcile

# 然后上传所有变更
icloud submit -a
```

## 常用场景

### 首次同步

```bash
icloud login -u your@icloud.com
icloud list Documents -r           # 查看有哪些文件
icloud sync -f Documents -w 16     # 高速同步
```

### 日常编辑

```bash
vim notes.md                       # 编辑文件
icloud submit notes.md             # 上传修改
```

### 批量上传

```bash
icloud submit *.py                 # 上传所有 Python 文件
```

## 性能优化

```bash
# 使用更多并发线程（默认 8）
icloud sync -w 16

# 限制递归深度
icloud sync -d 1                   # 只同步顶层

# 默认跳过 .git, node_modules 等文件夹
# 如需同步这些文件夹：
icloud sync --no-exclude
```

## 故障排除

### 登录失败

```bash
# 清除缓存重新登录
rm -rf ~/.pyicloud
icloud logout
icloud login -u your@icloud.com
```

### 双因素认证

登录时会自动检测是否需要 2FA，按提示输入验证码即可。

### 中国大陆账号

工具会自动尝试国际和中国大陆端点，无需手动配置。

## 依赖

- Python 3.8+
- pyicloud
- click
- keyring

## License

MIT License
