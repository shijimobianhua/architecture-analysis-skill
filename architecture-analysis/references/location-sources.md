# 地点定位与真实底图 · 3.0

仅在区位/场地需要获取或更换底图时读取。本流程接在既有区位路线前，不新增子skill或Agent，不对每单增加联网要求。内容、字体、风格、画幅与分层规则仍以总入口为准。

## 选择与定位

- 优先复用客户底图或本单已核验素材。缺图时从任务书提取城市、地址/路口、相对方位、地标；也可使用客户经纬度或地图链接。确定所需范围和表达问题，再选来源。
- 国内地址优先已配置的高德Web服务（环境变量`AMAP_WEB_KEY`）；没有密钥可用现有搜索/浏览工具查看地图页面，核对地址及周边关系并按该来源允许的方式取得图像。搜索缩略图或来源不明的网图不能直接作为精确底图。不能访问或缺必要授权时转用客户截图/总图，明确相应缺口，不假装下载成功。
- 地理编码只产生候选。核对城市、匹配级别、任务书中的道路交叉口/水体/地标和路口哪一侧；粗粒度或同名结果不能自动选第一个。材料足够可核验后继续；会改变分析的歧义才问用户。用`point`记录选定位置和具体证据；工具保存证据不等于独立证实。
- 经纬度顺序固定经度、纬度；保留WGS84、GCJ02、BD09等原始体系。坐标未知先查来源；不凭数值猜体系。高德需要GCJ02，可用工具显式转换WGS84/BD09并保存转换链。ArcGIS本工具接收WGS84或EPSG:3857，不能把GCJ02改名后直接套用。
- 定位点/POI与用地红线分开：客户红线、CAD或清楚的任务书边界才支持画项目范围。公开地图上的街区轮廓不能冒充项目边界。不得根据卫星屋顶自行认定功能、产权、入口或可通行路径。

## 地图与卫星选择

- 道路层级、设施与到达联系用普通地图；地表肌理、水体、绿地、周边建成环境用卫星图。按问题选择，必要时才组合，不默认下载两种或做多套候选。
- 高德静态图仅接普通地图，不能添加未经支持的参数宣称取到卫星图。卫星可使用有访问/导出条件的ArcGIS MapServer（含用户服务），或地图平台正式提供的卫星页面/导出能力。浏览器可用时也可访问高德官方卫星图层；不绕过平台限制抓取私有瓦片。
- ArcGIS工具是通用导出适配器，没有内置无限免费商用服务。先查所选服务的覆盖、分辨率、导出能力、署名及用途；密钥/令牌从环境读取，不放技能、命令行参数值、订单或客户包。不代注册/购买服务。
- 若有来源要求的署名、版权标志、审图信息，按要求在图片中保留。黑白灰化、描绘或裁切须在来源允许的范围内进行，不能擦除必要标识来满足“无标题”。不将仅供技术测试的服务材料当可商用素材。

## 共坐标制作

原始底图保持原生像素另存，记录实际返回的图幅、范围、体系、来源、获取时间；拍摄日期查不到留null，不把下载日期当卫星拍摄日期。API响应和地图标签可能有错误或滞后，仍与当前任务书交叉核对。

ArcGIS以服务**实际返回extent**为准，服务可能为匹配画幅调整请求范围。高德静态图按中心/zoom/scale记录推定范围，除中心外的点位需控制点核对；工具不会把投影计算标成核验通过。核对至少两处可识别位置（宜分布在图内不同位置），与任务书的相对关系一致后，在本单geometry记录写明证据和结果；有偏差先修正坐标/范围再绘制。

把地图等比放到最终画布中的一个明确框，底图、项目点、道路覆盖与文字共享同一变换。`project`可将WGS84/GCJ02点转换到该框的像素位置，拒绝体系混用、图外点和改变长宽比；它不自动验证地点、图面留白或标签遮挡。裁切/旋转需另存相应变换，不能继续沿用原框的点位。最终仍检查标签越界、路径依据与有效图形覆盖画幅。

插画风可以体现在地图简化、线条、灰度、符号及少量需要的地标插画上；真实道路、水体和节点关系固定。卫星转灰度不改变几何，不默认用AI重画整张底图。图形、分析线、色块与文字按既有分层交付，底图清晰度不足时换合适素材/范围，不靠300PPI元数据或放大宣称清晰。

原地图自带的路名/标注属于底图像素，不承诺符合本单字体规格或可单独改字。需要统一字体时选择允许的无标签底图、可合法使用的地理数据或经核对的简化表达，再独立绘制所需标签；不要擅自擦除必要来源信息。用户确认字号用于本单新制作的文字层。

投影坐标单位不直接当作真实地面米数；未经比例/投影与尺度核对，不输出精确比例尺或距离圈。步行时间还需要真实可通行路网与计算/客户结果，本次工具不做路线规划、调查、客流热力或模拟。

## 工具用法（由智能体执行，客户无需学习）

`"${CODEBUDDY_SKILL_DIR}/scripts/map_source.py"`需要Python 3.10+与Pillow；网络使用标准库。参数`--out`是内部路径，文件已有则保留；同一取图目录参数与图像哈希一致时离线复用，改范围/样式需新版本目录。

```text
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" geocode --city 长沙市 --address 芙蓉中路与营盘路交叉口 --out internal/geocode.json
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" point --lon 112.99 --lat 28.20 --crs WGS84 --label 项目位置 --evidence "仅为命令示例；正式任务填写真实任务书页码与核对关系" --out internal/location.json
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" convert --point internal/location.json --out internal/location-gcj02.json
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" amap --point internal/location-gcj02.json --zoom 15 --width 1000 --height 700 --scale 1 --usage-note "本单使用依据/来源条件" --out internal/map-v1
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" arcgis --service https://example.org/arcgis/rest/services/Imagery/MapServer --bbox 112.98 28.19 113.01 28.22 --bbox-crs WGS84 --width 1200 --height 800 --kind satellite --attribution "来源要求的署名" --usage-note "本单使用依据/来源条件" --out internal/satellite-v1
python "${CODEBUDDY_SKILL_DIR}/scripts/map_source.py" project --map internal/map-v1/map.json --points internal/points.json --box 20 20 1500 1050 --out internal/pixels.json
```

上述坐标、服务地址只是语法示例，不代表当前项目。`points.json`为数组，每项含`label`、`coordinates:[经度,纬度]`及`crs`，与底图体系一致。地图返回尺寸不等于最终画布；最终画幅仍来自用户尺寸图。工具不打印密钥；不能把开启详细网络调试的日志发给客户。

缺密钥不发动网络请求。每次工具调用请求预算30秒、单次socket超时10秒，不自动重试，不批量下载瓦片。该预算不是网络严格实时上限或出图承诺。每张图先用一个合适来源；失败或内容不够时最多尝试一个备用来源，不轮询平台、改关键词循环或反复导出。碰到认证/额度/权限拒绝立即换允许的路径；网络等待约一分钟仍取不到可用材料，就说明缺口并继续能做的工作。一次性配置服务可复用，不把全部来源说明送进每单上下文。

## 来源与能力边界

- [高德地理编码](https://developer.amap.com/api/webservice/guide/api/georegeo/)、[坐标转换](https://lbs.amap.com/api/webservice/guide/api/convert)、[静态地图](https://developer.amap.com/api/webservice/guide/api/staticmaps/)、[官方卫星图层](https://developer.amap.com/api/javascript-api-v2/guide/layers/official-layers)。高德API需要相应类型Key，静态图逻辑尺寸上限1024×1024，scale=2返回更多像素；仍以实际图像和控制点为准。
- [ArcGIS Export Map](https://developers.arcgis.com/rest/services-reference/enterprise/export-map/)返回extent与实际宽高，采用服务实际值做叠加，工具不会静默拼瓦片。具体服务许可与收费独立于该接口文档。

本次不接入通用公共Nominatim地址服务、不复制外部图片资产、不更改经验库算法。公开地图检索记录只留本单内部，是否长期积累依旧按用户同意；地址、底图不会自动进入经验库。

## 从底图到道路高亮
取图后依 [道路连续表达](road-highlights.md) 使用已核对几何或描绘整段选定道路，不用AI猜路。工具的地理点投影不能替代道路完整性检查；高亮终止、异高程和场地边界另核。道路延伸到显示框外正常裁切，不为普通line越界限制提前收笔；不因本功能多取地图或代做路网调查。
