---
name: 自带程序示例(command runtime)
slug: demo-command
version: 1.0.0
description: 演示技能包如何直接调用自带的可执行程序/脚本,而不是包内的 python 函数。
when_to_use: 你已有一个成熟的命令行工具(求解器后处理、内部 exe、老脚本)不想改写成函数时,照这个包的写法把它包进来。
triggers: [自带程序, command runtime, 外部程序, exe]
category: demo
tools:
  - name: column_stats
    title: 逐列统计(由自带脚本完成)
    description: 把数据交给包内的 bin/summarize.py,读回它写出的统计表
    runtime: command
    # 占位符会在运行时替换成真实路径:
    #   {input} 输入数据(parquet)  {input_csv} 同一份数据的 csv
    #   {output} 结果要写到这里     {params_json} 参数 json
    #   {pack}   技能包根目录
    command: ["python", "bin/summarize.py", "--in", "{input_csv}", "--out", "{output}", "--params", "{params_json}"]
    output_file: output.csv
    returns: dataframe
    params:
      top_n:
        type: integer
        default: 20
        description: 最多统计多少列
---

# 自带程序示例

这个包只做一件事:证明"**我有现成的程序,不想改**"也能接进来。

## 契约(你的程序只需要满足这三条)

1. 从命令行参数拿输入文件路径(`--in`),文件是一份表格(csv 或 parquet,你选);
2. 参数从 `--params` 指向的 JSON 文件里读(也可以从环境变量 `SKILL_PARAMS` 读);
3. 把结果写到 `--out` 指向的路径,扩展名决定格式(`.csv` / `.parquet` / `.json` / `.md`),
   并且**正常结束时退出码为 0**。

写不出结果文件、或退出码非 0,系统会把你的 stdout/stderr 原样带回给用户 —— 所以你的程序
把错误打印清楚,用户就能看懂。

## 安全边界(必须知道)

自带程序**不受静态检查约束**:它能做什么完全取决于这段程序本身。因此:

- 服务端必须显式打开 `SKILLS_ALLOW_COMMAND_RUNTIME=true`;
- 只有管理员能安装这类包;
- 安装报告里会明确标出 `trust: command`。

只有当这个程序是你自己写的、或来源可信时才这么用;否则请把逻辑改写成 python 工具
(`runtime: python`),那条路径有 import 白名单和沙箱。
