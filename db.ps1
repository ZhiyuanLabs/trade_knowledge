# 一键查看 / 修改业务数据库（SQLite，跑在 api 容器内）
#
# 用法（在项目根目录的 PowerShell）：
#   .\db.ps1                      # 总览：三张表行数 + 低库存清单
#   .\db.ps1 tables               # 列出所有表
#   .\db.ps1 products             # 查全部商品
#   .\db.ps1 orders               # 查全部订单
#   .\db.ps1 shipments            # 查全部入出荷
#   .\db.ps1 low                  # 查低库存商品
#   .\db.ps1 sql "SELECT ..."     # 任意查询（只读展示）
#   .\db.ps1 write "UPDATE ..."   # 执行增/改/删（会写入数据库）
#   .\db.ps1 refresh              # 重新拷一份 business_view.db 到本地，供 VSCode 双击查看
#
# 若提示“无法运行脚本”，改用：
#   powershell -ExecutionPolicy Bypass -File .\db.ps1 products

param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)

$root = $PSScriptRoot
Set-Location $root
$container = "nextjs-docs-rag-api-1"

# 容器是否在运行
$running = docker inspect -f '{{.State.Running}}' $container 2>$null
if ("$running" -ne "true") {
    Write-Host "容器 $container 没有在运行。请先在项目根执行：docker compose up -d" -ForegroundColor Red
    exit 1
}

$cmd = if ($CliArgs.Count -ge 1) { $CliArgs[0] } else { "summary" }

# refresh：把数据库拷到本地副本给 VSCode 图形化查看
if ($cmd -eq "refresh") {
    $dest = Join-Path $root "business_view.db"
    $src = $container + ":/app/data/business.db"
    docker cp $src $dest | Out-Null
    Write-Host "已更新只读副本：$dest" -ForegroundColor Green
    Write-Host "用 VSCode 的 SQLite Viewer 扩展双击即可查看（这是副本，不影响运行中的系统）。" -ForegroundColor Green
    exit 0
}

# 把最新查询脚本送进容器
$dbPy = Join-Path $root "db.py"
$dbPyDest = $container + ":/tmp/db.py"
docker cp $dbPy $dbPyDest | Out-Null

$out = Join-Path $root ".db_out.txt"

if ($cmd -eq "sql" -or $cmd -eq "write") {
    if ($CliArgs.Count -lt 2) {
        Write-Host "用法：.\db.ps1 sql `"SELECT ...`"   或   .\db.ps1 write `"UPDATE ...`"" -ForegroundColor Yellow
        exit 1
    }
    # 把 SQL 写进文件送进容器，彻底避开命令行引号/日文转义问题
    $sqlFile = Join-Path $root ".db_sql.txt"
    [System.IO.File]::WriteAllText($sqlFile, $CliArgs[1] + "`n", (New-Object System.Text.UTF8Encoding($false)))
    $sqlDest = $container + ":/tmp/db_sql.txt"
    docker cp $sqlFile $sqlDest | Out-Null
    Remove-Item $sqlFile -Force
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
docker exec $container python /tmp/db.py $cmd > $out 2>&1
Get-Content $out -Encoding UTF8
Remove-Item $out -Force
