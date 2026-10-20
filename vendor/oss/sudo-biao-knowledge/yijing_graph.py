"""
knowledge/yijing_graph.py
=========================
Complete I Ching (易经) + Chinese Metaphysics Knowledge Graph
Covers: 阴阳 → 四象 → 八卦 → 六十四卦 → 五行 → 天干地支 → 纳甲 → 河图洛书
"""

# ═══════════════════════════════════════════════════════════════
# 一、阴阳 (Yin-Yang Root)
# ═══════════════════════════════════════════════════════════════
YINYANG = {
    "太极": {"desc": "无极而太极，太极动而生阳，静而生阴", "generates": ["阳", "阴"]},
    "阳": {"symbol": "⚊", "nature": "刚健、光明、运动、向上", "number": 9},
    "阴": {"symbol": "⚋", "nature": "柔顺、暗昧、静止、向下", "number": 6},
}

# ═══════════════════════════════════════════════════════════════
# 二、四象 (Four Images)
# ═══════════════════════════════════════════════════════════════
SIXIANG = {
    "太阳": {"binary": "11", "element": "火", "season": "夏", "direction": "南"},
    "少阴": {"binary": "10", "element": "金", "season": "秋", "direction": "西"},
    "少阳": {"binary": "01", "element": "木", "season": "春", "direction": "东"},
    "太阴": {"binary": "00", "element": "水", "season": "冬", "direction": "北"},
}

# ═══════════════════════════════════════════════════════════════
# 三、八卦 (Eight Trigrams) — 先天/后天
# ═══════════════════════════════════════════════════════════════
BAGUA = {
    "乾": {"symbol":"☰","binary":"111","wuxing":"金","nature":"天","family":"父","body":"首","animal":"马","direction_xiantian":"南","direction_houtian":"西北","number_xiantian":1,"number_houtian":6,"luoshu":6},
    "兑": {"symbol":"☱","binary":"110","wuxing":"金","nature":"泽","family":"少女","body":"口","animal":"羊","direction_xiantian":"东南","direction_houtian":"西","number_xiantian":2,"number_houtian":7,"luoshu":7},
    "离": {"symbol":"☲","binary":"101","wuxing":"火","nature":"火","family":"中女","body":"目","animal":"雉","direction_xiantian":"东","direction_houtian":"南","number_xiantian":3,"number_houtian":9,"luoshu":9},
    "震": {"symbol":"☳","binary":"100","wuxing":"木","nature":"雷","family":"长男","body":"足","animal":"龙","direction_xiantian":"东北","direction_houtian":"东","number_xiantian":4,"number_houtian":3,"luoshu":3},
    "巽": {"symbol":"☴","binary":"011","wuxing":"木","nature":"风","family":"长女","body":"股","animal":"鸡","direction_xiantian":"西南","direction_houtian":"东南","number_xiantian":5,"number_houtian":4,"luoshu":4},
    "坎": {"symbol":"☵","binary":"010","wuxing":"水","nature":"水","family":"中男","body":"耳","animal":"豕","direction_xiantian":"西","direction_houtian":"北","number_xiantian":6,"number_houtian":1,"luoshu":1},
    "艮": {"symbol":"☶","binary":"001","wuxing":"土","nature":"山","family":"少男","body":"手","animal":"狗","direction_xiantian":"西北","direction_houtian":"东北","number_xiantian":7,"number_houtian":8,"luoshu":8},
    "坤": {"symbol":"☷","binary":"000","wuxing":"土","nature":"地","family":"母","body":"腹","animal":"牛","direction_xiantian":"北","direction_houtian":"西南","number_xiantian":8,"number_houtian":2,"luoshu":2},
}

# ═══════════════════════════════════════════════════════════════
# 四、五行 (Five Elements)
# ═══════════════════════════════════════════════════════════════
WUXING_SYSTEM = {
    "木": {"direction":"东","season":"春","color":"青","planet":"岁星(木星)","organ_zang":"肝","organ_fu":"胆","sense":"目","emotion":"怒","taste":"酸","number":"3,8","generates":"火","overcomes":"土","tiangan":["甲","乙"],"dizhi":["寅","卯"]},
    "火": {"direction":"南","season":"夏","color":"赤","planet":"荧惑(火星)","organ_zang":"心","organ_fu":"小肠","sense":"舌","emotion":"喜","taste":"苦","number":"2,7","generates":"土","overcomes":"金","tiangan":["丙","丁"],"dizhi":["巳","午"]},
    "土": {"direction":"中","season":"长夏","color":"黄","planet":"镇星(土星)","organ_zang":"脾","organ_fu":"胃","sense":"口","emotion":"思","taste":"甘","number":"5,10","generates":"金","overcomes":"水","tiangan":["戊","己"],"dizhi":["辰","戌","丑","未"]},
    "金": {"direction":"西","season":"秋","color":"白","planet":"太白(金星)","organ_zang":"肺","organ_fu":"大肠","sense":"鼻","emotion":"悲","taste":"辛","number":"4,9","generates":"水","overcomes":"木","tiangan":["庚","辛"],"dizhi":["申","酉"]},
    "水": {"direction":"北","season":"冬","color":"黑","planet":"辰星(水星)","organ_zang":"肾","organ_fu":"膀胱","sense":"耳","emotion":"恐","taste":"咸","number":"1,6","generates":"木","overcomes":"火","tiangan":["壬","癸"],"dizhi":["亥","子"]},
}

# ═══════════════════════════════════════════════════════════════
# 五、天干 (Ten Heavenly Stems)
# ═══════════════════════════════════════════════════════════════
TIANGAN_DETAIL = {
    "甲": {"wuxing":"木","yinyang":"阳","direction":"东","season":"春","organ":"胆","image":"参天大树","合":"己","冲":"庚"},
    "乙": {"wuxing":"木","yinyang":"阴","direction":"东","season":"春","organ":"肝","image":"花草藤蔓","合":"庚","冲":"辛"},
    "丙": {"wuxing":"火","yinyang":"阳","direction":"南","season":"夏","organ":"小肠","image":"太阳烈火","合":"辛","冲":"壬"},
    "丁": {"wuxing":"火","yinyang":"阴","direction":"南","season":"夏","organ":"心","image":"灯烛星火","合":"壬","冲":"癸"},
    "戊": {"wuxing":"土","yinyang":"阳","direction":"中","season":"长夏","organ":"胃","image":"城墙大山","合":"癸","冲":"甲"},
    "己": {"wuxing":"土","yinyang":"阴","direction":"中","season":"长夏","organ":"脾","image":"田园湿土","合":"甲","冲":"乙"},
    "庚": {"wuxing":"金","yinyang":"阳","direction":"西","season":"秋","organ":"大肠","image":"刀剑斧钺","合":"乙","冲":"丙"},
    "辛": {"wuxing":"金","yinyang":"阴","direction":"西","season":"秋","organ":"肺","image":"珠玉首饰","合":"丙","冲":"丁"},
    "壬": {"wuxing":"水","yinyang":"阳","direction":"北","season":"冬","organ":"膀胱","image":"江河大海","合":"丁","冲":"戊"},
    "癸": {"wuxing":"水","yinyang":"阴","direction":"北","season":"冬","organ":"肾","image":"雨露溪泉","合":"戊","冲":"己"},
}

# ═══════════════════════════════════════════════════════════════
# 六、地支 (Twelve Earthly Branches)
# ═══════════════════════════════════════════════════════════════
DIZHI_DETAIL = {
    "子": {"wuxing":"水","yinyang":"阳","hour":"23-01","month":11,"shengxiao":"鼠","season":"冬","canggan":["癸"],"sanhe":"申子辰","liuhe":"丑","chong":"午","direction":"北"},
    "丑": {"wuxing":"土","yinyang":"阴","hour":"01-03","month":12,"shengxiao":"牛","season":"冬","canggan":["己","癸","辛"],"sanhe":"巳酉丑","liuhe":"子","chong":"未","direction":"东北"},
    "寅": {"wuxing":"木","yinyang":"阳","hour":"03-05","month":1,"shengxiao":"虎","season":"春","canggan":["甲","丙","戊"],"sanhe":"寅午戌","liuhe":"亥","chong":"申","direction":"东北"},
    "卯": {"wuxing":"木","yinyang":"阴","hour":"05-07","month":2,"shengxiao":"兔","season":"春","canggan":["乙"],"sanhe":"亥卯未","liuhe":"戌","chong":"酉","direction":"东"},
    "辰": {"wuxing":"土","yinyang":"阳","hour":"07-09","month":3,"shengxiao":"龙","season":"春","canggan":["戊","乙","癸"],"sanhe":"申子辰","liuhe":"酉","chong":"戌","direction":"东南"},
    "巳": {"wuxing":"火","yinyang":"阴","hour":"09-11","month":4,"shengxiao":"蛇","season":"夏","canggan":["丙","戊","庚"],"sanhe":"巳酉丑","liuhe":"申","chong":"亥","direction":"东南"},
    "午": {"wuxing":"火","yinyang":"阳","hour":"11-13","month":5,"shengxiao":"马","season":"夏","canggan":["丁","己"],"sanhe":"寅午戌","liuhe":"未","chong":"子","direction":"南"},
    "未": {"wuxing":"土","yinyang":"阴","hour":"13-15","month":6,"shengxiao":"羊","season":"夏","canggan":["己","丁","乙"],"sanhe":"亥卯未","liuhe":"午","chong":"丑","direction":"西南"},
    "申": {"wuxing":"金","yinyang":"阳","hour":"15-17","month":7,"shengxiao":"猴","season":"秋","canggan":["庚","壬","戊"],"sanhe":"申子辰","liuhe":"巳","chong":"寅","direction":"西南"},
    "酉": {"wuxing":"金","yinyang":"阴","hour":"17-19","month":8,"shengxiao":"鸡","season":"秋","canggan":["辛"],"sanhe":"巳酉丑","liuhe":"辰","chong":"卯","direction":"西"},
    "戌": {"wuxing":"土","yinyang":"阳","hour":"19-21","month":9,"shengxiao":"狗","season":"秋","canggan":["戊","辛","丁"],"sanhe":"寅午戌","liuhe":"卯","chong":"辰","direction":"西北"},
    "亥": {"wuxing":"水","yinyang":"阴","hour":"21-23","month":10,"shengxiao":"猪","season":"冬","canggan":["壬","甲"],"sanhe":"亥卯未","liuhe":"寅","chong":"巳","direction":"西北"},
}

# ═══════════════════════════════════════════════════════════════
# 七、六十四卦 (64 Hexagrams) — 完整易经
# ═══════════════════════════════════════════════════════════════
HEXAGRAM_64 = [
    {"num":1,"name":"乾","upper":"乾","lower":"乾","symbol":"䷀","judgment":"元亨利贞","image":"天行健，君子以自强不息","nature":"纯阳至刚"},
    {"num":2,"name":"坤","upper":"坤","lower":"坤","symbol":"䷁","judgment":"元亨，利牝马之贞","image":"地势坤，君子以厚德载物","nature":"纯阴至柔"},
    {"num":3,"name":"屯","upper":"坎","lower":"震","symbol":"䷂","judgment":"元亨利贞，勿用有攸往","image":"云雷屯，君子以经纶","nature":"万物始生"},
    {"num":4,"name":"蒙","upper":"艮","lower":"坎","symbol":"䷃","judgment":"亨，匪我求童蒙，童蒙求我","image":"山下出泉，蒙，君子以果行育德","nature":"蒙昧启智"},
    {"num":5,"name":"需","upper":"坎","lower":"乾","symbol":"䷄","judgment":"有孚，光亨，贞吉，利涉大川","image":"云上于天，需，君子以饮食宴乐","nature":"等待时机"},
    {"num":6,"name":"讼","upper":"乾","lower":"坎","symbol":"䷅","judgment":"有孚窒惕，中吉，终凶","image":"天与水违行，讼，君子以作事谋始","nature":"争讼之道"},
    {"num":7,"name":"师","upper":"坤","lower":"坎","symbol":"䷆","judgment":"贞，丈人吉，无咎","image":"地中有水，师，君子以容民畜众","nature":"统兵之道"},
    {"num":8,"name":"比","upper":"坎","lower":"坤","symbol":"䷇","judgment":"吉，原筮元永贞，无咎","image":"地上有水，比，先王以建万国亲诸侯","nature":"亲比团结"},
    {"num":9,"name":"小畜","upper":"巽","lower":"乾","symbol":"䷈","judgment":"亨，密云不雨，自我西郊","image":"风行天上，小畜，君子以懿文德","nature":"小有蓄止"},
    {"num":10,"name":"履","upper":"乾","lower":"兑","symbol":"䷉","judgment":"履虎尾，不咥人，亨","image":"上天下泽，履，君子以辨上下定民志","nature":"履行礼仪"},
    {"num":11,"name":"泰","upper":"坤","lower":"乾","symbol":"䷊","judgment":"小往大来，吉，亨","image":"天地交，泰，后以财成天地之道","nature":"天地交泰"},
    {"num":12,"name":"否","upper":"乾","lower":"坤","symbol":"䷋","judgment":"否之匪人，不利君子贞","image":"天地不交，否，君子以俭德辟难","nature":"天地不交"},
    {"num":13,"name":"同人","upper":"乾","lower":"离","symbol":"䷌","judgment":"同人于野，亨，利涉大川","image":"天与火，同人，君子以类族辨物","nature":"志同道合"},
    {"num":14,"name":"大有","upper":"离","lower":"乾","symbol":"䷍","judgment":"元亨","image":"火在天上，大有，君子以遏恶扬善","nature":"大有所获"},
    {"num":15,"name":"谦","upper":"坤","lower":"艮","symbol":"䷎","judgment":"亨，君子有终","image":"地中有山，谦，君子以裒多益寡","nature":"谦逊之德"},
    {"num":16,"name":"豫","upper":"震","lower":"坤","symbol":"䷏","judgment":"利建侯行师","image":"雷出地奋，豫，先王以作乐崇德","nature":"喜悦豫乐"},
    {"num":17,"name":"随","upper":"兑","lower":"震","symbol":"䷐","judgment":"元亨利贞，无咎","image":"泽中有雷，随，君子以向晦入宴息","nature":"随顺时势"},
    {"num":18,"name":"蛊","upper":"艮","lower":"巽","symbol":"䷑","judgment":"元亨，利涉大川","image":"山下有风，蛊，君子以振民育德","nature":"整治腐败"},
    {"num":19,"name":"临","upper":"坤","lower":"兑","symbol":"䷒","judgment":"元亨利贞，至于八月有凶","image":"泽上有地，临，君子以教思无穷","nature":"居上临下"},
    {"num":20,"name":"观","upper":"巽","lower":"坤","symbol":"䷓","judgment":"盥而不荐，有孚颙若","image":"风行地上，观，先王以省方观民设教","nature":"观察省察"},
    {"num":21,"name":"噬嗑","upper":"离","lower":"震","symbol":"䷔","judgment":"亨，利用狱","image":"雷电噬嗑，先王以明罚敕法","nature":"明罚敕法"},
    {"num":22,"name":"贲","upper":"艮","lower":"离","symbol":"䷕","judgment":"亨，小利有攸往","image":"山下有火，贲，君子以明庶政","nature":"文饰之美"},
    {"num":23,"name":"剥","upper":"艮","lower":"坤","symbol":"䷖","judgment":"不利有攸往","image":"山附于地，剥，上以厚下安宅","nature":"剥落衰落"},
    {"num":24,"name":"复","upper":"坤","lower":"震","symbol":"䷗","judgment":"亨，出入无疾，朋来无咎","image":"雷在地中，复，先王以至日闭关","nature":"一阳来复"},
    {"num":25,"name":"无妄","upper":"乾","lower":"震","symbol":"䷘","judgment":"元亨利贞，其匪正有眚","image":"天下雷行，物与无妄","nature":"无妄之行"},
    {"num":26,"name":"大畜","upper":"艮","lower":"乾","symbol":"䷙","judgment":"利贞，不家食吉，利涉大川","image":"天在山中，大畜，君子以多识前言往行","nature":"大有蓄积"},
    {"num":27,"name":"颐","upper":"艮","lower":"震","symbol":"䷚","judgment":"贞吉，观颐，自求口实","image":"山下有雷，颐，君子以慎言语节饮食","nature":"养正之道"},
    {"num":28,"name":"大过","upper":"兑","lower":"巽","symbol":"䷛","judgment":"栋桡，利有攸往，亨","image":"泽灭木，大过，君子以独立不惧","nature":"大过之时"},
    {"num":29,"name":"坎","upper":"坎","lower":"坎","symbol":"䷜","judgment":"习坎，有孚维心亨","image":"水洊至，习坎，君子以常德行习教事","nature":"重重险难"},
    {"num":30,"name":"离","upper":"离","lower":"离","symbol":"䷝","judgment":"利贞亨，畜牝牛吉","image":"明两作离，大人以继明照于四方","nature":"光明附丽"},
    {"num":31,"name":"咸","upper":"兑","lower":"艮","symbol":"䷞","judgment":"亨利贞，取女吉","image":"山上有泽，咸，君子以虚受人","nature":"感应相通"},
    {"num":32,"name":"恒","upper":"震","lower":"巽","symbol":"䷟","judgment":"亨，无咎利贞，利有攸往","image":"雷风恒，君子以立不易方","nature":"恒久之道"},
    {"num":33,"name":"遁","upper":"乾","lower":"艮","symbol":"䷠","judgment":"亨，小利贞","image":"天下有山，遁，君子以远小人","nature":"退避隐遁"},
    {"num":34,"name":"大壮","upper":"震","lower":"乾","symbol":"䷡","judgment":"利贞","image":"雷在天上，大壮，君子以非礼弗履","nature":"阳刚壮盛"},
    {"num":35,"name":"晋","upper":"离","lower":"坤","symbol":"䷢","judgment":"康侯用锡马蕃庶","image":"明出地上，晋，君子以自昭明德","nature":"光明上进"},
    {"num":36,"name":"明夷","upper":"坤","lower":"离","symbol":"䷣","judgment":"利艰贞","image":"明入地中，明夷，君子以莅众用晦而明","nature":"韬光养晦"},
    {"num":37,"name":"家人","upper":"巽","lower":"离","symbol":"䷤","judgment":"利女贞","image":"风自火出，家人，君子以言有物而行有恒","nature":"家道正伦"},
    {"num":38,"name":"睽","upper":"离","lower":"兑","symbol":"䷥","judgment":"小事吉","image":"上火下泽，睽，君子以同而异","nature":"乖违背离"},
    {"num":39,"name":"蹇","upper":"坎","lower":"艮","symbol":"䷦","judgment":"利西南，不利东北","image":"山上有水，蹇，君子以反身修德","nature":"行路艰难"},
    {"num":40,"name":"解","upper":"震","lower":"坎","symbol":"䷧","judgment":"利西南，无所往","image":"雷雨作，解，君子以赦过宥罪","nature":"解除困难"},
    {"num":41,"name":"损","upper":"艮","lower":"兑","symbol":"䷨","judgment":"有孚元吉无咎","image":"山下有泽，损，君子以惩忿窒欲","nature":"减损克己"},
    {"num":42,"name":"益","upper":"巽","lower":"震","symbol":"䷩","judgment":"利有攸往，利涉大川","image":"风雷益，君子以见善则迁","nature":"增益进取"},
    {"num":43,"name":"夬","upper":"兑","lower":"乾","symbol":"䷪","judgment":"扬于王庭，孚号有厉","image":"泽上于天，夬，君子以施禄及下","nature":"决断刚毅"},
    {"num":44,"name":"姤","upper":"乾","lower":"巽","symbol":"䷫","judgment":"女壮，勿用取女","image":"天下有风，姤，后以施命诰四方","nature":"不期而遇"},
    {"num":45,"name":"萃","upper":"兑","lower":"坤","symbol":"䷬","judgment":"亨，王假有庙","image":"泽上于地，萃，君子以除戎器戒不虞","nature":"聚合萃集"},
    {"num":46,"name":"升","upper":"坤","lower":"巽","symbol":"䷭","judgment":"元亨，用见大人","image":"地中生木，升，君子以顺德积小以高大","nature":"上升进步"},
    {"num":47,"name":"困","upper":"兑","lower":"坎","symbol":"䷮","judgment":"亨，贞大人吉","image":"泽无水，困，君子以致命遂志","nature":"困穷之境"},
    {"num":48,"name":"井","upper":"坎","lower":"巽","symbol":"䷯","judgment":"改邑不改井，无丧无得","image":"木上有水，井，君子以劳民劝相","nature":"养人之源"},
    {"num":49,"name":"革","upper":"兑","lower":"离","symbol":"䷰","judgment":"己日乃孚，元亨利贞","image":"泽中有火，革，君子以治历明时","nature":"变革创新"},
    {"num":50,"name":"鼎","upper":"离","lower":"巽","symbol":"䷱","judgment":"元吉亨","image":"木上有火，鼎，君子以正位凝命","nature":"鼎新革故"},
    {"num":51,"name":"震","upper":"震","lower":"震","symbol":"䷲","judgment":"亨，震来虩虩","image":"洊雷震，君子以恐惧修省","nature":"震动奋起"},
    {"num":52,"name":"艮","upper":"艮","lower":"艮","symbol":"䷳","judgment":"艮其背不获其身","image":"兼山艮，君子以思不出其位","nature":"止而能止"},
    {"num":53,"name":"渐","upper":"巽","lower":"艮","symbol":"䷴","judgment":"女归吉，利贞","image":"山上有木，渐，君子以居贤德善俗","nature":"循序渐进"},
    {"num":54,"name":"归妹","upper":"震","lower":"兑","symbol":"䷵","judgment":"征凶，无攸利","image":"泽上有雷，归妹，君子以永终知敝","nature":"少女归嫁"},
    {"num":55,"name":"丰","upper":"震","lower":"离","symbol":"䷶","judgment":"亨，王假之","image":"雷电皆至，丰，君子以折狱致刑","nature":"丰盛光大"},
    {"num":56,"name":"旅","upper":"离","lower":"艮","symbol":"䷷","judgment":"小亨，旅贞吉","image":"山上有火，旅，君子以明慎用刑","nature":"旅行羁旅"},
    {"num":57,"name":"巽","upper":"巽","lower":"巽","symbol":"䷸","judgment":"小亨，利有攸往","image":"随风巽，君子以申命行事","nature":"柔顺入微"},
    {"num":58,"name":"兑","upper":"兑","lower":"兑","symbol":"䷹","judgment":"亨利贞","image":"丽泽兑，君子以朋友讲习","nature":"喜悦和乐"},
    {"num":59,"name":"涣","upper":"巽","lower":"坎","symbol":"䷺","judgment":"亨，王假有庙","image":"风行水上，涣，先王以享于帝立庙","nature":"涣散离散"},
    {"num":60,"name":"节","upper":"坎","lower":"兑","symbol":"䷻","judgment":"亨，苦节不可贞","image":"泽上有水，节，君子以制数度议德行","nature":"节制有度"},
    {"num":61,"name":"中孚","upper":"巽","lower":"兑","symbol":"䷼","judgment":"豚鱼吉，利涉大川","image":"泽上有风，中孚，君子以议狱缓死","nature":"诚信中正"},
    {"num":62,"name":"小过","upper":"震","lower":"艮","symbol":"䷽","judgment":"亨利贞，可小事","image":"山上有雷，小过，君子以行过乎恭","nature":"小有过越"},
    {"num":63,"name":"既济","upper":"坎","lower":"离","symbol":"䷾","judgment":"亨小利贞，初吉终乱","image":"水在火上，既济，君子以思患而预防之","nature":"事已成就"},
    {"num":64,"name":"未济","upper":"离","lower":"坎","symbol":"䷿","judgment":"亨，小狐汔济","image":"火在水上，未济，君子以慎辨物居方","nature":"事未完成"},
]

# ═══════════════════════════════════════════════════════════════
# 八、河图洛书 (Hetu-Luoshu)
# ═══════════════════════════════════════════════════════════════
HETU = {
    "一六共宗": {"number": [1,6], "wuxing": "水", "direction": "北"},
    "二七同道": {"number": [2,7], "wuxing": "火", "direction": "南"},
    "三八为朋": {"number": [3,8], "wuxing": "木", "direction": "东"},
    "四九为友": {"number": [4,9], "wuxing": "金", "direction": "西"},
    "五十同途": {"number": [5,10], "wuxing": "土", "direction": "中"},
}

LUOSHU = {
    "magic_square": [[4,9,2],[3,5,7],[8,1,6]],
    "center": 5,
    "sum": 15,
    "九宫飞星": {
        1: {"name":"一白贪狼","wuxing":"水","direction":"北","nature":"桃花·智慧"},
        2: {"name":"二黑巨门","wuxing":"土","direction":"西南","nature":"病符·困厄"},
        3: {"name":"三碧禄存","wuxing":"木","direction":"东","nature":"是非·口舌"},
        4: {"name":"四绿文曲","wuxing":"木","direction":"东南","nature":"文昌·学业"},
        5: {"name":"五黄廉贞","wuxing":"土","direction":"中","nature":"灾煞·凶星"},
        6: {"name":"六白武曲","wuxing":"金","direction":"西北","nature":"权贵·武职"},
        7: {"name":"七赤破军","wuxing":"金","direction":"西","nature":"口舌·破败"},
        8: {"name":"八白左辅","wuxing":"土","direction":"东北","nature":"财运·吉星"},
        9: {"name":"九紫右弼","wuxing":"火","direction":"南","nature":"喜庆·桃花"},
    },
}

# ═══════════════════════════════════════════════════════════════
# 九、知识图谱边关系 (Graph Edges)
# ═══════════════════════════════════════════════════════════════
def build_graph():
    """Build complete knowledge graph as {nodes:[], edges:[]}"""
    nodes = []
    edges = []
    
    # Layer 0: 太极
    nodes.append({"id":"太极","label":"太极","layer":0,"category":"root","size":30})
    
    # Layer 1: 阴阳
    for name in ["阳","阴"]:
        nodes.append({"id":name,"label":name,"layer":1,"category":"yinyang","size":22})
        edges.append({"source":"太极","target":name,"relation":"生"})
    
    # Layer 2: 四象
    for name, data in SIXIANG.items():
        nodes.append({"id":name,"label":name,"layer":2,"category":"sixiang","size":16,"wuxing":data["element"]})
        parent = "阳" if data["binary"][0] == "1" else "阴"
        edges.append({"source":parent,"target":name,"relation":"分"})
    
    # Layer 3: 八卦
    for name, data in BAGUA.items():
        nodes.append({"id":f"卦_{name}","label":name,"layer":3,"category":"bagua","size":14,"symbol":data["symbol"],"wuxing":data["wuxing"],"nature":data["nature"]})
        # Connect to sixiang
        b = data["binary"]
        sixiang_key = {"11":"太阳","10":"少阴","01":"少阳","00":"太阴"}.get(b[:2])
        if sixiang_key:
            edges.append({"source":sixiang_key,"target":f"卦_{name}","relation":"演"})
    
    # Layer 4: 五行
    for name, data in WUXING_SYSTEM.items():
        nodes.append({"id":f"行_{name}","label":name,"layer":4,"category":"wuxing","size":18,"direction":data["direction"],"color_hint":data["color"]})
        # 相生 edges
        edges.append({"source":f"行_{name}","target":f"行_{data['generates']}","relation":"生"})
        # 相克 edges
        edges.append({"source":f"行_{name}","target":f"行_{data['overcomes']}","relation":"克"})
        # 八卦→五行
        for gua_name, gua_data in BAGUA.items():
            if gua_data["wuxing"] == name:
                edges.append({"source":f"卦_{gua_name}","target":f"行_{name}","relation":"属"})
    
    # Layer 5: 天干
    for name, data in TIANGAN_DETAIL.items():
        nodes.append({"id":f"干_{name}","label":name,"layer":5,"category":"tiangan","size":10,"wuxing":data["wuxing"],"yinyang":data["yinyang"]})
        edges.append({"source":f"行_{data['wuxing']}","target":f"干_{name}","relation":"化"})
    
    # Layer 5: 地支
    for name, data in DIZHI_DETAIL.items():
        nodes.append({"id":f"支_{name}","label":name,"layer":5,"category":"dizhi","size":10,"wuxing":data["wuxing"],"shengxiao":data["shengxiao"]})
        edges.append({"source":f"行_{data['wuxing']}","target":f"支_{name}","relation":"化"})
    
    # Layer 6: 64卦 (connect to 八卦)
    for h in HEXAGRAM_64:
        nodes.append({"id":f"卦64_{h['num']}","label":h["name"],"layer":6,"category":"hexagram64","size":6,"symbol":h.get("symbol",""),"judgment":h["judgment"],"image":h["image"],"nature":h.get("nature","")})
        edges.append({"source":f"卦_{h['upper']}","target":f"卦64_{h['num']}","relation":"上卦"})
        edges.append({"source":f"卦_{h['lower']}","target":f"卦64_{h['num']}","relation":"下卦"})
    
    # 河图洛书 → 五行
    for _, data in HETU.items():
        edges.append({"source":f"行_{data['wuxing']}","target":"太极","relation":"河图"})

    # ── Layer 7: 十神 (Ten Gods) ──
    SHISHEN = {
        "比肩":{"wuxing_rel":"同我阳","desc":"同类帮扶，自立独立"},
        "劫财":{"wuxing_rel":"同我阴","desc":"竞争争财，决断魄力"},
        "食神":{"wuxing_rel":"我生阳","desc":"才华发泄，口福享乐"},
        "伤官":{"wuxing_rel":"我生阴","desc":"创新突破，不守规矩"},
        "正财":{"wuxing_rel":"我克阴","desc":"踏实求财，正职薪资"},
        "偏财":{"wuxing_rel":"我克阳","desc":"意外之财，投资偏业"},
        "正官":{"wuxing_rel":"克我阴","desc":"管束有方，功名仕途"},
        "七杀":{"wuxing_rel":"克我阳","desc":"威权压力，军警武职"},
        "正印":{"wuxing_rel":"生我阴","desc":"学识修养，长辈庇护"},
        "偏印":{"wuxing_rel":"生我阳","desc":"偏门学艺，枭神夺食"},
    }
    for name, data in SHISHEN.items():
        nodes.append({"id":f"神_{name}","label":name,"layer":7,"category":"shishen","size":8,"desc":data["desc"]})
    # Connect 十神 to 太极 (they derive from 五行 生克)
    for wx in ["木","火","土","金","水"]:
        edges.append({"source":f"行_{wx}","target":f"神_比肩","relation":"同类"})
    edges.append({"source":f"神_食神","target":f"神_伤官","relation":"同源"})
    edges.append({"source":f"神_正财","target":f"神_偏财","relation":"同源"})
    edges.append({"source":f"神_正官","target":f"神_七杀","relation":"同源"})
    edges.append({"source":f"神_正印","target":f"神_偏印","relation":"同源"})
    edges.append({"source":f"神_比肩","target":f"神_劫财","relation":"同源"})

    # ── Layer 7: 十格 (Ten Classical Patterns) ──
    SHIGE = ["正官格","七杀格","正财格","偏财格","食神格","伤官格","正印格","偏印格","建禄格","阳刃格"]
    for ge in SHIGE:
        ss = ge.replace("格","")
        nodes.append({"id":f"格_{ge}","label":ge,"layer":7,"category":"gejv","size":7,"desc":f"子平真诠八格之一"})
        if f"神_{ss}" in [n["id"] for n in nodes]:
            edges.append({"source":f"神_{ss}","target":f"格_{ge}","relation":"成格"})

    # ── Layer 7: 十二长生 ──
    CHANGSHENG = ["长生","沐浴","冠带","临官","帝旺","衰","病","死","墓","绝","胎","养"]
    for i, cs in enumerate(CHANGSHENG):
        nodes.append({"id":f"生_{cs}","label":cs,"layer":7,"category":"changsheng","size":6,"desc":f"十二长生第{i+1}位"})
        if i > 0:
            edges.append({"source":f"生_{CHANGSHENG[i-1]}","target":f"生_{cs}","relation":"转"})
    edges.append({"source":f"生_养","target":f"生_长生","relation":"轮回"})
    # Connect to 五行
    edges.append({"source":"行_木","target":"生_长生","relation":"木长生于亥"})
    edges.append({"source":"行_火","target":"生_帝旺","relation":"火旺于午"})

    # ── Layer 7: 二十四节气 ──
    JIEQI = [
        ("立春","寅","木"),("雨水","寅","木"),("惊蛰","卯","木"),("春分","卯","木"),
        ("清明","辰","土"),("谷雨","辰","土"),("立夏","巳","火"),("小满","巳","火"),
        ("芒种","午","火"),("夏至","午","火"),("小暑","未","土"),("大暑","未","土"),
        ("立秋","申","金"),("处暑","申","金"),("白露","酉","金"),("秋分","酉","金"),
        ("寒露","戌","土"),("霜降","戌","土"),("立冬","亥","水"),("小雪","亥","水"),
        ("大雪","子","水"),("冬至","子","水"),("小寒","丑","土"),("大寒","丑","土"),
    ]
    for jq, zhi, wx in JIEQI:
        nodes.append({"id":f"节_{jq}","label":jq,"layer":7,"category":"jieqi","size":5,"dizhi":zhi,"wuxing":wx})
        edges.append({"source":f"支_{zhi}","target":f"节_{jq}","relation":"司令"})

    # ── Layer 8: 纳音五行 (30 unique) ──
    NAYIN_30 = {
        "海中金":"金","炉中火":"火","大林木":"木","路旁土":"土","剑锋金":"金",
        "山头火":"火","涧下水":"水","城头土":"土","白蜡金":"金","杨柳木":"木",
        "泉中水":"水","屋上土":"土","霹雳火":"火","松柏木":"木","长流水":"水",
        "沙中金":"金","山下火":"火","平地木":"木","壁上土":"土","金箔金":"金",
        "佛灯火":"火","天河水":"水","大驿土":"土","钗环金":"金","桑拓木":"木",
        "大溪水":"水","沙中土":"土","天上火":"火","石榴木":"木","大海水":"水",
    }
    for name, wx in NAYIN_30.items():
        nodes.append({"id":f"音_{name}","label":name,"layer":8,"category":"nayin","size":4,"wuxing":wx})
        edges.append({"source":f"行_{wx}","target":f"音_{name}","relation":"纳音"})

    # ── Layer 8: 紫微十四主星 ──
    ZIWEI_STARS = {
        "紫微":{"wx":"土","nature":"帝座之星，百官之主"},
        "天机":{"wx":"木","nature":"智慧之星，善于谋略"},
        "太阳":{"wx":"火","nature":"光明之星，博爱利他"},
        "武曲":{"wx":"金","nature":"财星将星，刚毅果断"},
        "天同":{"wx":"水","nature":"福星懒星，与世无争"},
        "廉贞":{"wx":"火","nature":"次桃花，事业心强"},
        "天府":{"wx":"土","nature":"财库之星，沉稳大方"},
        "太阴":{"wx":"水","nature":"富贵之星，温柔细腻"},
        "贪狼":{"wx":"木","nature":"桃花之星，多才多艺"},
        "巨门":{"wx":"水","nature":"暗曜口舌，善辩分析"},
        "天相":{"wx":"水","nature":"印星宰辅，谨慎周到"},
        "天梁":{"wx":"土","nature":"荫星清贵，乐善好施"},
        "七杀星":{"wx":"金","nature":"将星孤克，开创之力"},
        "破军":{"wx":"水","nature":"耗星破旧，变革创新"},
    }
    for name, data in ZIWEI_STARS.items():
        nodes.append({"id":f"星_{name}","label":name,"layer":8,"category":"ziwei_star","size":5,"wuxing":data["wx"],"nature":data["nature"]})
        edges.append({"source":f"行_{data['wx']}","target":f"星_{name}","relation":"五行属"})

    # ── Layer 8: 奇门九星 + 八门 + 八神 ──
    QIMEN_XING = {"天蓬":"水","天芮":"土","天冲":"木","天辅":"木","天禽":"土","天心":"金","天柱":"金","天任":"土","天英":"火"}
    for name, wx in QIMEN_XING.items():
        nodes.append({"id":f"奇星_{name}","label":name,"layer":8,"category":"qimen_star","size":5,"wuxing":wx})
        edges.append({"source":f"行_{wx}","target":f"奇星_{name}","relation":"属"})

    QIMEN_MEN = {"休门":"水","死门":"土","伤门":"木","杜门":"木","开门":"金","惊门":"金","生门":"土","景门":"火"}
    for name, wx in QIMEN_MEN.items():
        nodes.append({"id":f"门_{name}","label":name,"layer":8,"category":"qimen_door","size":5,"wuxing":wx})
        edges.append({"source":f"行_{wx}","target":f"门_{name}","relation":"属"})

    QIMEN_SHEN = ["值符","腾蛇","太阴","六合","白虎","玄武","九地","九天"]
    for name in QIMEN_SHEN:
        nodes.append({"id":f"神将_{name}","label":name,"layer":8,"category":"qimen_shen","size":4})

    # ── Layer 8: 六爻六亲 + 六神 ──
    LIUQIN = {"父母":"生我","兄弟":"同我","子孙":"我生","妻财":"我克","官鬼":"克我"}
    for name, rel in LIUQIN.items():
        nodes.append({"id":f"亲_{name}","label":name,"layer":8,"category":"liuyao_qin","size":5,"desc":f"六亲·{rel}"})

    LIUSHEN = {"青龙":"木","朱雀":"火","勾陈":"土","腾蛇":"火","白虎":"金","玄武":"水"}
    for name, wx in LIUSHEN.items():
        nodes.append({"id":f"兽_{name}","label":name,"layer":8,"category":"liuyao_shen","size":5,"wuxing":wx})
        edges.append({"source":f"行_{wx}","target":f"兽_{name}","relation":"属"})

    # ── Layer 8: 核心神煞 ──
    KEY_SHENSHA = {
        "天乙贵人":"遇难呈祥，贵人相助",
        "文昌贵人":"智慧聪颖，利于学业",
        "驿马":"奔波流动，利于远行",
        "华盖":"孤高有才，利文艺宗教",
        "羊刃":"刚猛凶悍，双刃之力",
        "桃花":"风流多情，异性缘旺",
        "天德贵人":"行善积德，逢凶化吉",
        "月德贵人":"阴柔之德，暗中庇佑",
        "禄神":"正禄之位，衣食丰足",
        "空亡":"虚无之象，有名无实",
    }
    for name, desc in KEY_SHENSHA.items():
        nodes.append({"id":f"煞_{name}","label":name,"layer":8,"category":"shensha","size":4,"desc":desc})

    # ── Additional edges: 天干合冲 ──
    for gan, data in TIANGAN_DETAIL.items():
        if data.get("合"):
            edges.append({"source":f"干_{gan}","target":f"干_{data['合']}","relation":"合"})

    # ── Additional edges: 地支三合六合六冲 ──
    SANHE = [("申","子","辰","水"),("寅","午","戌","火"),("巳","酉","丑","金"),("亥","卯","未","木")]
    for a,b,c,wx in SANHE:
        edges.append({"source":f"支_{a}","target":f"支_{b}","relation":"三合"})
        edges.append({"source":f"支_{b}","target":f"支_{c}","relation":"三合"})
        edges.append({"source":f"行_{wx}","target":f"支_{b}","relation":"三合局"})

    for name, data in DIZHI_DETAIL.items():
        if data.get("liuhe"):
            edges.append({"source":f"支_{name}","target":f"支_{data['liuhe']}","relation":"六合"})
        if data.get("chong"):
            edges.append({"source":f"支_{name}","target":f"支_{data['chong']}","relation":"冲"})

    # ── 洛书九宫飞星 → 方位 ──
    for num, star in LUOSHU["九宫飞星"].items():
        nodes.append({"id":f"飞_{num}","label":star["name"],"layer":8,"category":"feixing","size":4,"wuxing":star["wuxing"],"nature":star["nature"]})
        edges.append({"source":f"行_{star['wuxing']}","target":f"飞_{num}","relation":"属"})

    # ── 四象/四灵 (Four Sacred Beasts) ──
    SILING = {
        "青龙":{"wx":"木","dir":"东","season":"春","xiu":"角亢氐房心尾箕"},
        "朱雀":{"wx":"火","dir":"南","season":"夏","xiu":"井鬼柳星张翼轸"},
        "白虎":{"wx":"金","dir":"西","season":"秋","xiu":"奎娄胃昴毕觜参"},
        "玄武":{"wx":"水","dir":"北","season":"冬","xiu":"斗牛女虚危室壁"},
    }
    for name, data in SILING.items():
        nodes.append({"id":f"灵_{name}","label":name,"layer":7,"category":"siling","size":7,
            "wuxing":data["wx"],"direction":data["dir"],"desc":f"{data['dir']}方{data['season']}·统{data['xiu']}"})
        edges.append({"source":f"行_{data['wx']}","target":f"灵_{name}","relation":"象"})

    # ── 二十八星宿 (28 Lunar Mansions) ──
    XINGXIU = [
        ("角","木","蛟","青龙"),("亢","金","龙","青龙"),("氐","土","貉","青龙"),("房","日","兔","青龙"),
        ("心","月","狐","青龙"),("尾","火","虎","青龙"),("箕","水","豹","青龙"),
        ("井","木","犴","朱雀"),("鬼","金","羊","朱雀"),("柳","土","獐","朱雀"),("星","日","马","朱雀"),
        ("张","月","鹿","朱雀"),("翼","火","蛇","朱雀"),("轸","水","蚓","朱雀"),
        ("奎","木","狼","白虎"),("娄","金","狗","白虎"),("胃","土","雉","白虎"),("昴","日","鸡","白虎"),
        ("毕","月","乌","白虎"),("觜","火","猴","白虎"),("参","水","猿","白虎"),
        ("斗","木","獬","玄武"),("牛","金","牛","玄武"),("女","土","蝠","玄武"),("虚","日","鼠","玄武"),
        ("危","月","燕","玄武"),("室","火","猪","玄武"),("壁","水","貐","玄武"),
    ]
    for xiu, wx, qin, siling in XINGXIU:
        nodes.append({"id":f"宿_{xiu}","label":xiu,"layer":9,"category":"xingxiu","size":3,
            "wuxing":wx,"desc":f"{xiu}{wx}{qin}·{siling}七宿"})
        edges.append({"source":f"灵_{siling}","target":f"宿_{xiu}","relation":"统"})

    # ── 十二生肖 ──
    SHENGXIAO_LIST = [
        ("鼠","子"),("牛","丑"),("虎","寅"),("兔","卯"),("龙","辰"),("蛇","巳"),
        ("马","午"),("羊","未"),("猴","申"),("鸡","酉"),("狗","戌"),("猪","亥"),
    ]
    for sx, zhi in SHENGXIAO_LIST:
        nodes.append({"id":f"肖_{sx}","label":sx,"layer":8,"category":"shengxiao","size":4,"dizhi":zhi})
        edges.append({"source":f"支_{zhi}","target":f"肖_{sx}","relation":"配"})

    # ── 紫微十二宫 ──
    ZIWEI_GONG = ["命宫","兄弟宫","夫妻宫","子女宫","财帛宫","疾厄宫",
                  "迁移宫","交友宫","官禄宫","田宅宫","福德宫","父母宫"]
    for gong in ZIWEI_GONG:
        nodes.append({"id":f"宫_{gong}","label":gong,"layer":9,"category":"ziwei_gong","size":3,"desc":"紫微十二宫之一"})

    # ── 紫微辅星/煞星 ──
    ZIWEI_AUX = {
        "文昌":"金","文曲":"水","左辅":"土","右弼":"水",
        "天魁":"火","天钺":"火","禄存":"土","天马":"火",
        "火星":"火","铃星":"火","擎羊":"金","陀罗":"金",
    }
    for name, wx in ZIWEI_AUX.items():
        nodes.append({"id":f"辅_{name}","label":name,"layer":9,"category":"ziwei_aux","size":3,"wuxing":wx})
        edges.append({"source":f"行_{wx}","target":f"辅_{name}","relation":"属"})

    # ── 三元九运 ──
    SANYUAN = [
        ("一运","上元","水",1864,1883),("二运","上元","土",1884,1903),("三运","上元","木",1904,1923),
        ("四运","中元","木",1924,1943),("五运","中元","土",1944,1963),("六运","中元","金",1964,1983),
        ("七运","下元","金",1984,2003),("八运","下元","土",2004,2023),("九运","下元","火",2024,2043),
    ]
    for name, yuan, wx, y1, y2 in SANYUAN:
        nodes.append({"id":f"运_{name}","label":name,"layer":9,"category":"sanyuan","size":3,
            "wuxing":wx,"desc":f"{yuan}·{y1}-{y2}年"})
        edges.append({"source":f"行_{wx}","target":f"运_{name}","relation":"当运"})

    # ── 建除十二神 (Twelve Day Officers) ──
    JIANCHU = ["建","除","满","平","定","执","破","危","成","收","开","闭"]
    JIANCHU_JX = {"建":"中","除":"吉","满":"中","平":"中","定":"吉","执":"中","破":"凶","危":"凶","成":"吉","收":"吉","开":"吉","闭":"凶"}
    for name in JIANCHU:
        nodes.append({"id":f"直_{name}","label":name,"layer":9,"category":"jianchu","size":3,
            "desc":f"建除十二神·{JIANCHU_JX.get(name,'')}"})

    # ── 黄道十二神 ──
    HUANGDAO = {
        "青龙":"吉·百事皆宜","明堂":"吉·修造安葬","天刑":"凶·诸事不宜","朱雀":"凶·口舌是非",
        "金匮":"吉·纳财开市","天德":"吉·万事大吉","白虎":"凶·血光之灾","玉堂":"吉·求名求利",
        "天牢":"凶·犯罪入狱","玄武":"凶·盗贼失物","司命":"吉·安床定灶","勾陈":"凶·官讼缠身",
    }
    for name, desc in HUANGDAO.items():
        nodes.append({"id":f"道_{name}","label":name,"layer":9,"category":"huangdao","size":3,"desc":desc})

    # ── 天干五合化 (edges) ──
    HEHUA = [("甲","己","土"),("乙","庚","金"),("丙","辛","水"),("丁","壬","木"),("戊","癸","火")]
    for a, b, wx in HEHUA:
        edges.append({"source":f"干_{a}","target":f"干_{b}","relation":f"合化{wx}"})

    # ── 地支六害 (edges) ──
    LIUHAI = [("子","未"),("丑","午"),("寅","巳"),("卯","辰"),("申","亥"),("酉","戌")]
    for a, b in LIUHAI:
        edges.append({"source":f"支_{a}","target":f"支_{b}","relation":"害"})

    # ── 地支三刑 (edges) ──
    edges.append({"source":"支_寅","target":"支_巳","relation":"刑"})
    edges.append({"source":"支_巳","target":"支_申","relation":"刑"})
    edges.append({"source":"支_申","target":"支_寅","relation":"刑"})
    edges.append({"source":"支_子","target":"支_卯","relation":"刑"})
    edges.append({"source":"支_卯","target":"支_子","relation":"刑"})
    edges.append({"source":"支_丑","target":"支_戌","relation":"刑"})
    edges.append({"source":"支_戌","target":"支_未","relation":"刑"})
    edges.append({"source":"支_未","target":"支_丑","relation":"刑"})

    return {"nodes": nodes, "edges": edges}
