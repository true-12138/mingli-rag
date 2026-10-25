#命理古籍RAG|项目开发日志
##D1
背景
目标：在 CloudStudio 搭建RAG项目环境，D1任务：创建venv虚拟环境、安装jieba分词、项目初始化并提交Git，日志存入GitHub可追踪目录。
遇到的问题 & 解决方案
问题1：CloudStudio 使用「从Git仓库导入」创建项目，报 disk create failed
• 现象：粘贴Github仓库地址直接新建应用失败，磁盘资源报错。
• 原因：CloudStudio免费版预分配磁盘的资源配额不足，该创建方式会一次性申请整块磁盘，容易失败。
• 解决办法：
1. 先新建空白Python模板应用；
2. 将Github仓库临时改为Public公开，绕过私有仓库授权校验；
3. 在空白环境终端使用git clone拉取项目代码。
问题2：Git提交时报错 Author identity unknown
• 现象：执行git commit，提示未配置用户身份，无法提交。
• 尝试：使用--global全局配置用户名邮箱，在CloudStudio容器环境不生效。
• 解决办法：只针对当前仓库本地配置（不带--global）
问题3：配置身份后依然提示 nothing to commit, working tree clean
• 现象：安装完jieba，想git提交，但Git提示没有任何改动，无法commit。
• 原因：
pip install jieba只是修改CloudStudio容器内venv环境；
venv文件夹一般被git忽略，不会被Git追踪。安装包属于运行环境变更，不会修改仓库里任何源码/文档文件，Git感知不到变化。
• 解决办法：新建文档文件，制造可被git追踪的文件改动。
选择规范工程方案：创建docs/目录，在里面放开发日志daily_dev_journal.md。新增md文档属于仓库文件变更，可以正常提交push到Github。
问题4：疑问：venv里面装了jieba，为什么Git看不到？
• 知识点：
1. venv是云服务器上的本地隔离Python环境，jieba真实安装路径：venv/lib/python/site-packages；
2. Git一般通过.gitignore忽略venv/文件夹，不会上传巨大的环境文件到GitHub；
3. 环境是运行时载体，不属于项目源码。后续更换容器环境，venv会丢失，需要依靠requirements.txt重新安装依赖（放到项目依赖稳定后再导出）。
问题5：日志存放位置选择
需求：日志要能提交、保存到GitHub，不能只存在容器本地（容器重启就丢）。
方案：遵循工程规范，放在docs/daily_dev_journal.md，专门存放项目文档、开发日志、踩坑记录。D2需要的问题清单后续也放在docs目录。
问题 5：D盘推了代码，但GitHub上找不到新增的脚本？
现象：在D盘终端执行 git push origin main 提示 Everything up-to-date（一切最新），但去GitHub网页上死活看不到 _scripts 下新增的脚本。
原因：分支错位。AI在D盘工作时建了一个名叫 corpus-tooling 的平行分支，你的新代码实际提交在这个分支里。而你推向了 main（主分支），自然找不到。
解决：
  1. 在D盘终端确认分支：git status。
  2. 推送正确分支：git push origin corpus-tooling。
  3. 去GitHub网页，点击左上角默认的 main 下拉框，切换到 corpus-tooling 分支，就能看到了。

问题 6：云端拉取代码报错“Authentication failed”（认证失败）
现象：在云端终端执行 git fetch origin，爆红报错：fatal: Authentication failed for 'https://github.com/...'，并提示 Missing or invalid credentials。
原因：GitHub 早已禁用账号密码验证。云端（Cloud Studio）访问 GitHub 需要专用的 Personal Access Token (PAT) 作为密码。
解决：
  1. 生成Token：去 GitHub 网页生成 Token。注意！要进入账号的个人设置（右上角头像 -> Settings -> Developer settings -> Personal access tokens），不要去仓库（Repository）的 Settings 里找。勾选 repo 权限，生成后复制 ghp_ 开头的字符串。
  2. 云端配置：在云端终端执行 git remote set-url origin https://你的GitHub用户名:刚才复制的ghp_密码@github.com/true-12138/mingli-rag.git。
  3. 再次执行 git fetch origin，成功连接。

问题 7：云端执行切换分支命令各种翻车
现象：云端执行 git checkout corpus-tooling 报错。第一次提示 error: pathspec 'corpus-tooling' did not match any file(s) known to git；第二次手敲时提示 git: 'checkou' is not a git command。
原因：
  1. 第一次报错：云端本地没同步分支列表，它不知道有这个分支，必须先联网拉取分支信息，才能切过去。
  2. 第二次报错：纯粹是手滑输入漏了字母（漏了 t，变成了 checkou），终端报错。
· 解决：
  1. 先执行 git fetch origin，让云端从 GitHub 拉取最新分支列表（成功的话会看到绿色提示 * [new branch] corpus-tooling -> origin/corpus-tooling）。
  2. 完整、正确地敲击：git checkout corpus-tooling。
  3. 成功切换，终端提示符从 git:(main) 变成 git:(corpus-tooling)。
##D2
今日任务写Python脚本遍历古籍txt，统计每本文件行数、字符、标点数量，输出csv统计表格。
一、遇到的Bug + 解决方案
1. ModuleNotFoundError: No module named 'pandas'
问题：当前激活的虚拟环境venv没有安装pandas库
解决：pip install pandas
3. TypeError: Bookstat.init() takes 6 positional arguments but 7 were given（核心报错）
问题：dataclass定义的字段数量，和return实例时传入参数数量不匹配；同时变量名不一致（total_char vs total_chars）
解决：在Bookstat类补充缺失字段pure_text_chars:int，保证传参个数、变量名称一一对应。
二、本次新学到的知识点
1. Pathlib路径相关
Path("xxx").parent：拿到文件所在文件夹路径
.mkdir(parents=True, exist_ok=True)：
parents=True：多层父目录不存在时，递归创建
exist_ok=True：目录已经存在，不会抛异常（工程必备写法）
绝对路径 /workspace/xxx VS 相对路径 workspace/xxx：绝对路径不受终端当前工作目录干扰，推荐CloudStudio开发使用。
2. dataclass 数据类
@dataclass 自动生成构造函数__init__
硬性规则：实例化传入参数数量、顺序、变量名必须和类定义完全匹配，多传/少传/名字写错直接TypeError。
对象.__dict__：把实例所有字段转为字典，pd.DataFrame可以接收字典列表，快速生成表格。
3. 文件读取的细节
f.readlines()：读取文件，返回字符串列表，每一行作为列表元素，自带\n换行符
"".join(lines)：拼接列表里所有字符串，得到单个长字符串；字符串内部保留换行符\n，len()统计的是字符串内字符数量，不是行数。
len(lines)：统计文件行数（列表元素个数）
4. Pandas小常识
pd.DataFrame([字典列表])：字典的key自动成为表格列，value作为每行数据
.to_csv()：仅负责写入文件，不会自动新建文件夹，这是高频踩坑点。
5. CloudStudio开发习惯
修改代码后一定要Ctrl+S保存，否则运行的是旧代码，改了半天不生效。
虚拟环境venv隔离依赖：包必须装在当前激活的venv里面，全局安装的包在venv里看不见。