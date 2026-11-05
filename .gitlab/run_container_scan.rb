# Preserve complete scanner diagnostics without overflowing the CI trace limit.
require 'json'
require 'fileutils'

FileUtils.mkdir_p('out')
FileUtils.rm_f(['gl-container-scanning-report.json', 'gl-sbom-report.cdx.json', 'tmp.json'])
log = 'out/container-scan.log'
puts 'Running complete container vulnerability and SBOM scans; full diagnostics retained as an artifact'
pid = Process.spawn('gtcs', 'scan', out: log, err: log)
_, status = Process.wait2(pid)
summary = { scanner_exit: status.exitstatus, signal: status.termsig }
begin
  report = JSON.parse(File.read('gl-container-scanning-report.json'))
  sbom = JSON.parse(File.read('gl-sbom-report.cdx.json'))
  summary[:scan_status] = report.fetch('scan').fetch('status')
  summary[:findings] = report.fetch('vulnerabilities').length
  summary[:sbom_components] = sbom.fetch('components').length
rescue StandardError => error
  summary[:report_error] = error.message
end
puts JSON.generate(summary)
if !status.success? || summary[:scan_status] != 'success' || !summary[:sbom_components].to_i.positive?
  File.open(log, 'rb') do |stream|
    stream.seek([stream.size - 16_384, 0].max)
    puts stream.read.force_encoding('UTF-8').scrub
  end
  exit 1
end
