# Fetch only the hash-pinned, public toolchain archive; no Docker socket is needed.
require 'net/http'
require 'uri'
require 'digest'
require 'fileutils'
require 'zlib'

settings = File.readlines('.gitlab/toolchain.env', chomp: true).to_h { |line| line.split('=', 2) }
version = settings.fetch('NATIVE_TOOLCHAIN_VERSION')
expected = settings.fetch('NATIVE_TOOLCHAIN_SHA256')
raise 'Invalid toolchain pin' unless version.match?(/\A[0-9a-f]{20}\z/) && expected.match?(/\A[0-9a-f]{64}\z/)
uri = URI("#{ENV.fetch('CI_API_V4_URL')}/projects/#{ENV.fetch('CI_PROJECT_ID')}/packages/generic/native-toolchain/#{version}/toolchain.tar.gz")
http = Net::HTTP.new(uri.host, uri.port)
http.use_ssl = uri.scheme == 'https'
http.open_timeout = 20
http.read_timeout = 120
request = Net::HTTP::Get.new(uri)
request['JOB-TOKEN'] = ENV.fetch('CI_JOB_TOKEN')
FileUtils.mkdir_p('out')
partial = 'out/toolchain.tar.gz.new'
begin
  digest = Digest::SHA256.new
  count = 0
  http.request(request) do |response|
    raise "Toolchain download HTTP #{response.code}" unless response.is_a?(Net::HTTPSuccess)
    File.open(partial, 'wb') do |stream|
      response.read_body do |block|
        count += block.bytesize
        raise 'Toolchain archive exceeds 2 GiB bound' if count > 2 * 1024**3
        digest.update(block)
        stream.write(block)
      end
    end
  end
  raise 'Toolchain archive checksum mismatch' unless digest.hexdigest == expected
  File.rename(partial, 'out/toolchain.tar.gz')
  puts "Toolchain archive verified: #{version}, #{count} bytes"
  # GCS reads archive metadata for every finding. A seekable tar avoids
  # decompressing the entire image thousands of times during report conversion.
  expanded = 'out/toolchain.tar.new'
  begin
    size = 0
    Zlib::GzipReader.open('out/toolchain.tar.gz') do |source|
      File.open(expanded, 'wb') do |target|
        while (block = source.read(1024 * 1024)) && !block.empty?
          size += block.bytesize
          raise 'Expanded toolchain archive exceeds 6 GiB bound' if size > 6 * 1024**3
          target.write(block)
        end
      end
    end
    File.rename(expanded, 'out/toolchain.tar')
    puts "Seekable toolchain archive ready: #{size} bytes"
  ensure
    File.unlink(expanded) if File.exist?(expanded)
  end
ensure
  File.unlink(partial) if File.exist?(partial)
end
