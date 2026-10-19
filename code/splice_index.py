# -*- coding: utf-8 -*-
"""splice_index.py —— 用新 INDEX(设计令牌版) 替换 app.py 的 INDEX，JS 原样迁移+清理"""
import re, sys, io

APP = "app.py"
NEW = "new_index.txt"

src = io.open(APP, encoding="utf-8").read()
new_tpl = io.open(NEW, encoding="utf-8").read()

start = src.index('INDEX = r"""') + len('INDEX = r"""')
end = src.index('"""', start)
old = src[start:end]
assert "<script>" in old and "</style>" in old

# ---- 1) 提取旧 JS ----
js = old[old.index("<script>") + len("<script>"): old.rindex("</script>")]

# ---- 2) 清理 theme 残留（applyTheme/themeBtn 整块）----
pat = re.compile(
    r'function applyTheme\(t\)\{document\.body\.classList\.toggle\("theme-glass",t==="glass"\);\n'
    r' \$\("themeBtn"\)\.textContent=t==="glass"\?"🌿":"🧊";localStorage\.setItem\("fg_theme",t\);\}\n'
    r'\$\("themeBtn"\)\.onclick=\(\)=>applyTheme\(localStorage\.getItem\("fg_theme"\)==="glass"\?"warm":"glass"\);\n'
    r'applyTheme\(localStorage\.getItem\("fg_theme"\)\|\|"warm"\);\n')
js, n = pat.subn("", js)
assert n == 1, "theme 块替换数=%d" % n

# ---- 3) JS 类名对齐新组件 ----
js = js.replace("class='avc mcd'", "class='card mcd'")
js = js.replace("class='gcard'", "class='card gcard'")
js = js.replace(
    '"<div class=\'kchead\'><div class=\'kctitle\'>这餐热量</div></div>"+\n'
    '   "<div class=\'avbig\'>"+tot("kcal")+" <small>千卡</small></div>"+\n'
    '   "<div class=\'kctagrow\'><div class=\'kctag\'>今天 "+avMeal+"</div></div>";',
    '"<div class=\'text-heading\'>这餐热量</div>"+\n'
    '   "<div class=\'text-huge-cal\'>"+tot("kcal")+" <span class=\'text-unit\'>千卡</span></div>"+\n'
    '   "<div style=\'display:flex;justify-content:flex-end;margin-top:10px\'><span class=\'tag\'>今天 "+avMeal+"</span></div>";')
js = js.replace('mcard("蛋白质",tot("protein_g"),avDay.protein,avTarget.protein,"#2f8bff")',
                'mcard("蛋白质",tot("protein_g"),avDay.protein,avTarget.protein)')
js = js.replace('mcard("脂肪",tot("fat_g"),avDay.fat,avTarget.fat,"#8fc9ff")',
                'mcard("脂肪",tot("fat_g"),avDay.fat,avTarget.fat)')
js = js.replace('mcard("碳水",tot("carb_g"),avDay.carb,avTarget.carb,"#1b4b9e")',
                'mcard("碳水",tot("carb_g"),avDay.carb,avTarget.carb)')
js = js.replace("function mcard(label,mealVal,dayVal,target,color){",
                "function mcard(label,mealVal,dayVal,target){")
js = js.replace('<circle cx=\'32\' cy=\'32\' r=\'"+R+"\' fill=\'none\' stroke=\'#dfe9f5\' stroke-width=\'7\'/>',
                '<circle class=\'ring-track\' cx=\'32\' cy=\'32\' r=\'"+R+"\' fill=\'none\' stroke-width=\'7\'/>')
js = js.replace('<circle cx=\'32\' cy=\'32\' r=\'"+R+"\' fill=\'none\' stroke=\'"+color+"\' stroke-width=\'7\' stroke-linecap=\'round\' ',
                '<circle class=\'ring-fill\' cx=\'32\' cy=\'32\' r=\'"+R+"\' fill=\'none\' stroke-width=\'7\' stroke-linecap=\'round\' ')
js = js.replace("fill='#163A78'", "style='fill:var(--text-main)'")
for bad in ("applyTheme", "themeBtn", "#2f8bff", "#8fc9ff", "#1b4b9e", "#dfe9f5", "theme-glass"):
    assert bad not in js, "JS 残留: " + bad

# ---- 4) 提取旧 HTML 并调整 ----
html = old[old.rindex("</style></head><body>") + len("</style></head><body>"):]

fb_start = html.index('<div class="mback" id="fixBack"')
fb = html[fb_start:]
fb = fb[: fb.index("</div></div>") + len("</div></div>")]
html = html.replace(fb, "@@FIXBACK@@")          # 从旧位置移除（#av 外）

html = html.replace('<div id="av">', '<div class="view" data-theme="meal" id="av">')
html = html.replace('<div class="avc avimgc">', '<div class="card card--image">')
html = html.replace('<div class="avc" id="avKcal">', '<div class="card" id="avKcal">')
html = html.replace('<div class="avc" id="avItems">', '<div class="card" id="avItems">')
html = html.replace('<div class="gcard">', '<div class="card gcard">')

# fixBack 移入 #av 末尾（avbtns 之后、#av 收口之前）
anchor = '💾 保存记录</button></div>\n</div>'
assert anchor in html, "avbtns 锚点缺失"
html = html.replace(anchor, '💾 保存记录</button></div>\n' + fb + '\n</div>')

# themeBtn 按钮移除
html = html.replace('\n  <button class="gear" id="themeBtn" title="切换主题">🧊</button>', '')

# homeView 包裹：body 开 + clearBack 收口
html = html.replace("<body>", "<body>\n" + '<div class="view" data-theme="home" id="homeView">', 1)
html = html.replace('<div id="toast"></div>', '</div>\n<div id="toast"></div>', 1)

# ---- 5) 组装新 INDEX（新 CSS + 迁移后的 HTML/JS）----
head = new_tpl[: new_tpl.index("<script>")]
tail = new_tpl[new_tpl.index("</script></body></html>"):]
new_index = head + js + tail

# 自检：新页面不得再含旧硬编码
for bad in ("theme-glass", "#16a34a", "#2b8a3e", "#3ea0ff", "#aed2f5", "#0e7490", "avc ", "#1c7ed6"):
    assert bad not in new_index, "新 INDEX 残留: " + bad

out = src[:start] + new_index + src[end:]
io.open(APP, "w", encoding="utf-8").write(out)
print("拼接完成 | 新 INDEX 长度:", len(new_index), "| 原:", len(old))
