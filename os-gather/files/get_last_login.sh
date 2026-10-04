get_last_login() {
  u="$1"; t=""
  if command -v lastlog >/dev/null 2>&1; then
    line=$(lastlog -u "$u" 2>/dev/null | tail -1)
    if ! echo "$line" | grep -q "Never logged in"; then
      ds=$(echo "$line" | awk '{
        n=NF; if($n~/^[0-9]{4}$/){
          if($(n-1)~/^[+-][0-9]{4}$/) print $(n-4),$(n-3),$(n-2),$(n-1),$n
          else print $(n-3),$(n-2),$(n-1),$n}}')
      [ -n "$ds" ] && t=$(date -d "$ds" -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || true)
    fi
  fi
  if [ -z "$t" ] && command -v last >/dev/null 2>&1; then
    line=$(last -F -n 1 "$u" 2>/dev/null | head -1)
    if [ -n "$line" ] && ! echo "$line" | grep -qE "^(wtmp|$)"; then
      ds=$(echo "$line" | awk '{for(i=1;i<=NF;i++){if($i~/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/){print $i,$(i+1),$(i+2),$(i+3),$(i+4);break}}}')
      [ -n "$ds" ] && t=$(date -d "$ds" -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || true)
    fi
  fi
  if [ -z "$t" ] && command -v utmpdump >/dev/null 2>&1 && [ -f /var/log/wtmp ]; then
    ul=$(utmpdump /var/log/wtmp 2>/dev/null | grep "\[$u\]" | tail -1)
    if [ -n "$ul" ]; then
      ds=$(echo "$ul" | grep -oE '\[[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' | tr -d '[')
      [ -n "$ds" ] && t="${ds}Z"
    fi
  fi
  echo "${u}:${t:-null}"
}
