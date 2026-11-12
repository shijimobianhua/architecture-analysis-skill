# 分层工具 V2

需要Python 3.10+与Pillow，字体由环境提供。工具不理解图纸或自动证明风格，智能体仍按子skill执行内容和视觉验收。

```
python "${CODEBUDDY_SKILL_DIR}/scripts/layers.py" inspect blank.png
python "${CODEBUDDY_SKILL_DIR}/scripts/layers.py" compose internal/layer-spec.json delivery
python "${CODEBUDDY_SKILL_DIR}/scripts/layers.py" verify delivery
python "${CODEBUDDY_SKILL_DIR}/scripts/migrate_spec.py" internal/old-spec.json internal/new-spec.json
```

新compose必须schema_version=2.0，新输出目录不能已有manifest。旧交付manifest仍可verify，96PPI等历史文件无需修改。旧制作spec必须显式migrate；迁移在原spec旁保存新文件，保留像素几何与旧背景、像素字号，PPI升至至少300并把文字确认设为false；不得把迁移当提高旧素材质量。

## 最小V2输入
```json
{"schema_version":"2.0","canvas":{"image":"blank.png"},"typography":{"confirmed":true,"roles":{"body":{"font":"C:/Windows/Fonts/msyh.ttc","family":"Microsoft YaHei","weight":"regular","size":12,"unit":"pt"}}},"layers":[{"role":"text","operations":[{"type":"text","text_role":"body","xy":[60,50],"text":"便捷通行","color":"#333333","max_width":400}]}]}
```

confirmed由本单已明确规格或用户授权决定，不能自行标true跳过询问。每个文字操作必须text_role，不能用font/size/unit等覆盖确认值。字体文件缺失或文字越界会报错，不fallback或自动缩小。12pt在300PPI为50px，12px保持12px。

canvas.image只取尺寸，不取底色/PPI。可用width/height代替，二者并存需一致。background明确指定时优先；否则reference_background若prominent=true，必须decision=use或white；use还需color。没有显著参考背景时默认白色。dpi默认300，新订单必须>=300。不询问印刷物理尺寸，不自动放大画布。

## 图层与操作
顺序background、base、fills、lines、text，同类可细分。每层source是全画布RGBA，或用operations：rect/ellipse(box、fill/outline、width)、polygon(points)、line/arrow(points、color、width、可选dash)、text(xy、text、text_role、color、可选max_width)、image(path、box)。image等比装入box，默认不放大；来源不够清晰时不能用allow_upscale假装原生高清。颜色可为色值或RGBA数组。

透明背景、同坐标、正常混合、100%不透明度与V1相同；非背景层必须有真实透明空间，空层省略。source导入的文字也必须事先按确认规格绘制，helper不能从栅格来源证明字号或识别备注。

manifest保留统一像素/DPI/sRGB、原点、层顺序、文件哈希、Alpha边界，以及本单typography用于内部核验；默认客户包可移除字体文件绝对路径等内部信息，但保留导入所需的canvas和layers。完整图从交付层合成。verify核对包括最终图在内的PPI/配置、重组、透明度、顺序和尺寸；compose拒绝制作备注，内部记录另存。

## 可选内部预排工具
正式生图前按 [容量与密度](layout-density.md) 使用`python "${CODEBUDDY_SKILL_DIR}/scripts/layout_check.py" --spec internal/layer-spec.json --plan internal/layout-plan.json --out internal/layout-check-v1.json`；计划和报告为内部sidecar，不改变V2制作或客户分层接口。按最终字体检查文字框、分配区、标签碰撞，并按实际绘图操作与已核对锚点检查几何偏差。报告不判定理想密度、事实真伪或视觉质量；人工检查仍必需。

## 道路覆盖层
需要完整道路高亮时可用 [road_overlay.py](road-highlights.md) 直接生成原尺寸RGBA roads.png，再作为分析线条层source交给compose；正常只render一次，不要求先check再render重复执行。道路层先画完整路径再裁到显示框，普通line操作的越界规则不改。报告和原始几何仅留内部，最终合成仍由现有交付层完成。
