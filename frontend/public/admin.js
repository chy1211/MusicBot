/* r27-vue-rebuild: old installed shell hands off to the current canonical shell. */
if (!document.getElementById("app") && !sessionStorage.getItem("musicbot-shell-upgrade")) { sessionStorage.setItem("musicbot-shell-upgrade","1"); location.replace("/"); }
