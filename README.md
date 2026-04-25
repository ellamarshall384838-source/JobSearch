# AI Job Search Companion - 多智能体求职助手 Demo

本项目是一个基于 [AgentScope](https://github.com/agentscope/agentscope) 构建的纯本地多智能体系统 (Multi-Agent System) 演示版本，专为解决应届毕业生求职过程中的痛点而设计。

系统通过三个协作的 AI 智能体（JobMatcher, ResumeTailor, InterviewPrep）将混乱的求职过程转化为有条理的、按部就班的工作流。

## 🌟 核心智能体模块

1. **JobDiscovery & Matching (职位匹配)**: 解析用户背景，并从本地模拟数据库中匹配最适合的职位。
2. **Resume Tailoring (简历定制)**: 对比用户简历与目标职位，进行差距分析，提供修改建议。
3. **Interview Preparation (面试准备)**: 预测面试问题，并帮助用户使用 STAR 法则构建回答。

---

## ⚙️ 环境配置

1. **Python 环境**: 建议使用 Python 3.9 或以上版本。
2. **安装核心依赖**:
   本系统依赖于 AgentScope 框架，请在终端中执行以下命令安装：
   
   ```bash
   pip install agentscope
   ```

## 🦙 Ollama 本地模型配置指南
为了保护用户隐私并实现离线运行，本 Demo 采用了 Ollama 来部署本地开源大模型（如通义千问 Qwen 系列），并提供兼容 OpenAI 格式的 API。
1. **安装 Ollama**: 前往 Ollama 官方网站，下载并安装适用于您操作系统（Windows/macOS/Linux）的版本。安装完成后，Ollama 会自动在后台运行（默认端口为 11434）。
2. **拉取并启动模型**:
   打开终端（CMD/PowerShell），运行以下命令来拉取并启动模型。(注意：请确保拉取的模型名称与 demo.py 中配置的 model_name 完全一致)

   ```bash
   # 示例：拉取并运行 qwen3.5:4b 版本
   ollama run qwen3.5:4b
   ```

(如果代码中使用了其他模型，请替换为对应的 Ollama 模型标签，例如 llama3, qwen2.5:3b 等)
当终端出现 >>> 提示符时，说明本地模型已成功加载并就绪。

## 🚀 运行 Demo
确保 Ollama 服务正在后台运行后，在项目根目录执行以下命令启动求职助手：
  
  ```bash
  python demo.py
  ```

根据终端提示，输入您的背景摘要，即可体验多轮路由对话系统。

## 🗺️ 后续优化与演进方向 (Roadmap)
当前的 Demo 展示了 AgentScope 多智能体架构的基础能力。为了达到最终的项目目标，系统计划在未来进行以下深度优化：

1. **☁️ 更合理的路由逻辑**:

   当前状态: 完全依赖关键词指定下一个智能体。

   优化方案: 需要更换为更合理，更智能的路由逻辑，例如添加一个智能体专门负责路由、指定负责这一轮对话的智能体。

2. **🖥️ Web 交互界面 (UI 升级)**:

   当前状态: 终端命令行 (CLI) 交互。

   优化方案: 利用 AgentScope 自带的 Studio，或结合 Gradio / Streamlit 构建现代化的 Web 交互界面，提升产品的用户体验和商业可用性。
