#!/bin/bash

# Create a map of environment variables to be passed to the config map
# What we're trying to do here is figure out which environment variables
# were injected into the container (e.g., by balena) and
# pass those along to the Kubernetes containers. 
#
# We do this by diff'ing the environment variables that existed at container
# build time (we create env.txt in the Dockerfile) and the environment variables
# that currently exist. We assume those that differ from build time are injected
# and build the map here. It has a simple `key: value` format that we can
# use to create a config map in Kubernetes.

# We also support passing environment variables in via the command line or a file with
# the -e and -f flag. This is meant to be used when debugging outside the docker
# environment.

# Summary of terminology:
# - Passed through environment variables: These are the environment variables that were
#   created as part of running the container (e.g., by balena or `docker run -e var=val`).
# - Passed in environment variables: These are the environment variables that are passed in on the
#   command line or in a file (e.g., `-e var=val` or `-f env.txt`).
#
# In practice, we will usually only have one of these two types of environment variables but
# we support both for symmetry.

runtime_env=$(mktemp /tmp/runtime-env-XXXXXX)

cleanup() {
    rm -f "$runtime_env"
}
trap cleanup EXIT

###########################################################################
# Function for handling passed through environment variables
###########################################################################

generate_passed_through_env() {
  # If we don't have a file called env.txt, we assume this is outside of a container and 
  # we just leave this empty.
  if [ -e env.txt ]; then
    # `comm -13` shows the lines that are unique to the second file (the current environment)
    comm -13 <(cat env.txt|sort) <(printenv|grep -v '^_='|sort) > $runtime_env

    # Emit key/value pairs as NUL-delimited to safely handle quotes
    while IFS= read -r line; do
      key=$(echo $line | cut -d= -f1)
      value=$(echo $line | cut -d= -f2-)
      printf '%s\0%s\0' "$key" "$value"
    done < $runtime_env
  fi
}

###########################################################################
# Functions for handling passed in environment variables
###########################################################################

parse_single_var() {
  local expr="$1"
  IFS='=' read -r var_name var_value <<< "$expr"

  if [ -z "$var_name" ]; then
    echo "Variable name cannot be empty." >&2
    return 1
  fi

  if [ -z "$var_value" ]; then
    grep -q = <<< "$expr"
    if [ $? -ne 0 ]; then
      var_value=$(eval echo \$$var_name)
    fi
  fi

  printf '%s\0%s\0' "$var_name" "$var_value"
}

parse_var_file() {
  local file="$1"

  if [ ! -f "$file" ]; then
    echo "File $file does not exist." >&2
    return 1
  fi

  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    parse_single_var "$line"
  done < "$file"
}


generate_passed_in_env() {
  while getopts ":e:f:" opt; do
    case $opt in
      e)
        parse_single_var "$OPTARG"
        ;;
      f)
        parse_var_file "$OPTARG"
        ;;
      \?)
        echo "Invalid option: -$OPTARG" >&2
        exit 1
        ;;
      :)
        echo "Option -$OPTARG requires an argument." >&2
        exit 1
        ;;
    esac
  done

  shift $((OPTIND - 1))

  if [ $# -ne 0 ]; then
    echo "This script does not accept positional arguments." >&2
    exit 1
  fi
}

###########################################################################
# Main script execution starts here
###########################################################################

{
  generate_passed_through_env
  generate_passed_in_env "$@"
} | \
  python3 "$(dirname "$0")/env-to-yaml.py"
