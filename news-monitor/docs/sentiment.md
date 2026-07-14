# skill: sentiment-analysis
version: 1.0
output_fields: [sentiment, confidence, greed_index]

## 情感分析规则
- BULLISH：超预期盈利、降息预期上升、积极并购、政策利好
- BEARISH：加息预期、盈利下调、监管打压、宏观衰退信号、信用事件
- NEUTRAL：事实性报道，无明确方向性；或多空信号相互抵消

## greed_index
0=极度恐慌, 50=中性, 100=极度贪婪

参考锚点：
- VIX > 30、市场大幅下跌 → 0–30
- 横盘整理、数据中性 → 40–60
- 纳指新高、强劲就业 → 70–90
- 泡沫迹象、极端追涨 → 90–100

## confidence
对情感判断的确信度（0.0-1.0）。新闻信号混合或信息不足时应降低置信度。
