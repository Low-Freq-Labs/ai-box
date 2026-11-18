#!/bin/bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
fail() { printf '%s\n' "$*" >&2; exit 2; }
# Test the exact production parser without provisioning accounts.
source /dev/stdin <<< "$(sed -n '/^select_colour() {$/,/^}$/p' "$root/assets/create-agent")"
for colour in red orange yellow green blue purple pink '#000000' '#FFFFFF' '#a1b2c3' '#123456'; do
    select_colour "$colour"
    [[ $hex =~ ^#[0-9A-F]{6}$ && $rgb =~ ^[0-9]+\;[0-9]+\;[0-9]+$ ]]
    ((ansi>=16 && ansi<=255))
    printf 'PASS color=%s rgb=%s ansi=%s hex=%s\n' "$colour" "$rgb" "$ansi" "$hex"
done
select_colour '#a1b2c3'; [[ $rgb == '161;178;195' && $hex == '#A1B2C3' ]]
select_colour '#000000'; [[ $ansi == 16 ]]
select_colour '#FFFFFF'; [[ $ansi == 231 ]]
for colour in indigo violet '#FFF' '#1234567' '#GG0000' '123456' '#123456;id' ''; do
    if (select_colour "$colour") 2>/dev/null; then fail "accepted invalid color: $colour"; fi
done
printf 'PASS invalid and retired colors rejected\n'
