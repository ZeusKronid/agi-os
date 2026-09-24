# Live session shell. The prompt takes the terminal palette: 1 is the coral accent, 8 is Ink Dim.
[[ $- != *i* ]] && return
alias ls='ls --color=auto'
alias grep='grep --color=auto'
PS1='\[\e[31m\]\u\[\e[90m\]@\[\e[97m\]\h \[\e[37m\]\w \[\e[31m\]\$\[\e[0m\] '
