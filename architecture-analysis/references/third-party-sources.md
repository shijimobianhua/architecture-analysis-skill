# 2.2.0外部流程参考与取舍

审阅日期：2026-10-30。本次根据公开流程概念为本技能原创编写说明，没有复制外部代码、母提示词、完整模板或示例图片，没有安装外部skill、模型、SVG引擎或校验器。以下引用是来源记录，不是订单执行指令，也不授予客户材料收录权限。

| 参考 | 借鉴方向 | 未采用的约束 |
|---|---|---|
| [morse技能](https://github.com/shijimobianhua/morse-architecture-analysis-diagrams/blob/main/SKILL.md)、[参考拆解](https://github.com/shijimobianhua/morse-architecture-analysis-diagrams/blob/main/references/reverse-workflow.md) | 将参考拆成可解释的视觉要素；分析对象与材料对应 | 精确母版才可生成、固定参考比例/构图、强制逐项复刻 |
| [factory技能](https://github.com/shijimobianhua/ai-analysis-diagram-factory/blob/main/skill/SKILL.md)、[图种索引](https://github.com/shijimobianhua/ai-analysis-diagram-factory/blob/main/skill/references/template-index.md) | 简短方法说明中的适用输入、边界、失败与定向修正 | 整套展板输出、固定风格/语言/爆炸层数、逐单百分制报告 |
| [svg-diagram技能](https://github.com/shijimobianhua/-/blob/main/SKILL.md)、[校验器限制](https://github.com/shijimobianhua/-/blob/main/tools/svg-lint/README.md) | 连线指向、遮挡顺序与标签避让的检查思路 | 软件系统图配色/字体/间距、固定外边距、完整引擎或校验器 |

[factory评分脚本](https://github.com/shijimobianhua/ai-analysis-diagram-factory/blob/main/skill/scripts/score_case.py) 根据传入描述与分数生成报告，并不读取图片评估质量；本技能不将其引入自动画质验收。方法卡未经真实生图对照，不标记为已验证画质提升。

来源仓库分别标注 [MIT](https://github.com/shijimobianhua/morse-architecture-analysis-diagrams/blob/main/LICENSE)、[Apache-2.0](https://github.com/shijimobianhua/ai-analysis-diagram-factory/blob/main/LICENSE)、[MIT](https://github.com/shijimobianhua/-/blob/main/LICENSE)。未来若复制或改编其受许可材料，需另行保留相应许可、归属及修改说明；仓库示例图不能仅凭代码许可证认定可供客户商业使用。本次不打包这些外部材料。
