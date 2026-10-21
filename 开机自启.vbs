' 每日混音 —— 静默启动（无窗口）
' 用法：把本文件复制/拖到  shell:startup  文件夹（Win+R 输入 shell:startup 回车）
' 之后每次登录 Windows 都会在后台启动服务，不弹黑窗。
' 停止：双击项目里的 停止.bat
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\deepseekwork\dailymix"
sh.Run """C:\Users\weiaaa\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"" app.py --no-browser", 0, False
