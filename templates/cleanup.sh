$(header)
$(temporary_header)
# Parse the complete function before cleanup can remove this script.
cleanup() {
  :
$(remove_outputs)
$(remove_generated)
}
cleanup
