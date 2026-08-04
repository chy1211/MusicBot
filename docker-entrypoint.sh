#!/bin/sh

if [ ! -f "/musicbot/config/example_options.ini" ] ; then
    cp -r /musicbot/sample_config/* /musicbot/config
fi

# Pre-compile zh_TW .mo with our working po2mo.py before run.py's JIT
# (upstream's JIT uses polib which may produce empty .mo from our custom .po)
if [ -f "/musicbot/tools/po2mo.py" ]; then
    for po in /musicbot/i18n/zh_TW/LC_MESSAGES/*.po /musicbot/i18n/zh_CN/LC_MESSAGES/*.po; do
        [ -f "$po" ] && python3 /musicbot/tools/po2mo.py "$po" 2>/dev/null
    done
fi

exec python3 run.py "$@"
