if [[ "${BUILDSYS_REPORT_SUPPRESS:-0}" != 1 ]]; then
  python3 $(reporter) $(artifacts)
fi
