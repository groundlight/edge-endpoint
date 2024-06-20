# DO NOT ADD SHEBANG (#!/bin/bash) ABOVE
#
# This should be "source"d from your .bashrc or similar

source /etc/bash_completion

alias k=kubectl
source <(kubectl completion bash)
complete -F __start_kubectl k

# This makes "watch k get all" work
alias watch='watch -n 0.7 '
