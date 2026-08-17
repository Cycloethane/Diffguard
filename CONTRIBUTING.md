# 贡献指南

欢迎为 DiffGuard 贡献代码、文档或反馈！

## 环境

- Python 3.10+
- Windows 10 / 11

## 开发流程

```bash
# 克隆后安装依赖
pip install -r requirements.txt
pip install pytest

# 运行测试
python -m pytest tests -q

# 启动应用
python main.py
```

## 提交规范

- 使用简洁、描述性的提交信息（可用中文或英文）。
- 保持改动聚焦：一次提交解决一个问题。
- 新增/修改功能请附上相应单元测试。

## 代码结构

```
main.py                入口
bridge/                OpenCode 桥接层
core/                  核心逻辑（解析 / 审查 / 监控）
models/                数据模型与持久化
ui/                    界面
tests/                 单元测试
```

## 分支与 PR

1. 从 `main` 切出特性分支：`git checkout -b feat/xxx`
2. 提交并推送到你的 fork
3. 创建 Pull Request，描述改动与测试情况

## 协议

本项目使用 MIT 协议，见 [LICENSE](LICENSE)。
