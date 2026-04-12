# paper-importer

将学术论文导入 Obsidian，自动生成段落交错的中英文双语笔记。

支持 arXiv（主要来源），以及博客、期刊等任意网页。

## 效果示例

```markdown
## 1. Introduction

**【中文】** 近年来，大型语言模型在自然语言处理领域取得了显著进展...

**【English】** In recent years, large language models have made remarkable progress...

![Figure 1: The Transformer architecture](figures/fig1.png)
```

每篇论文生成一个文件夹：

```
Papers/
  1706.03762-attention-is-all-you-need/
    index.md      ← 双语对照正文（Obsidian 直接打开）
    paper.pdf     ← 原始 PDF
    figures/
      fig1.png
      fig2.png
```

## 安装

```bash
git clone <this-repo>
cd paper-importer
./install.sh
```

或手动安装：

```bash
pip install -e .
```

**要求：** Python 3.10+

## 配置

```bash
paper setup
```

会提示输入：
- Obsidian vault 路径（如 `/Users/yourname/ObsidianVault`）
- Anthropic API key
- Papers 子文件夹名（默认 `Papers`）

配置保存在 `~/.paper-importer/config.json`，换机器后重新运行 `paper setup` 即可。

## 使用

### 导入单篇

```bash
# arXiv 论文（URL 或 ID 均可）
paper add https://arxiv.org/abs/1706.03762
paper add 1706.03762

# 本地 PDF 文件
paper add /path/to/paper.pdf

# 博客或期刊文章（任意 URL）
paper add https://lilianweng.github.io/posts/2023-06-23-agent/

# 添加自定义标签
paper add 1706.03762 --tags nlp,transformer

# 不下载 PDF / 图表（加快速度）
paper add 1706.03762 --no-pdf --no-figures
```

### 批量导入

新建一个文本文件，每行一个来源：

```
# 注意力机制系列
1706.03762
1810.04805

# 博客
https://lilianweng.github.io/posts/2023-06-23-agent/

# 本地 PDF
/Users/yourname/Downloads/paper.pdf
```

然后运行：

```bash
paper batch papers.txt
```

一个失败不会中断其余的，最后会显示汇总报告。

### 生成索引页

```bash
paper index
```

在 `Papers/_index.md` 生成 Dataview 查询页，包含：
- 所有论文表格（按年份倒序）
- 按年份分组视图
- 最近导入
- 文章/博客列表

需要在 Obsidian 中安装 [Dataview](https://github.com/blacksmithgu/obsidian-dataview) 插件。

### 其他

```bash
paper config   # 查看当前配置
paper setup    # 重新配置
```

## 在新机器上部署

```bash
git clone <this-repo>
cd paper-importer
./install.sh
paper setup   # 重新配置 vault 路径和 API key
```

## 翻译说明

- 使用 Claude API（claude-opus-4-6，可通过 `--model` 修改）
- 按章节逐段翻译，保留专业术语和文献引用格式
- **翻译结果永久保存在本地**，之后打开 Obsidian 无需联网或调用 API

## 依赖

- [anthropic](https://github.com/anthropics/anthropic-sdk-python) — 翻译
- [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) — arXiv HTML 解析
- [trafilatura](https://trafilatura.readthedocs.io/) — 通用网页内容提取
- [click](https://click.palletsprojects.com/) — CLI 框架
- [requests](https://requests.readthedocs.io/) — HTTP 请求
