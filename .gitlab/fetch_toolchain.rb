# Fetch only the hash-pinned, public toolchain archive; no Docker socket is needed.
require 'net/http'
require 'uri'
require 'digest'
require 'fileutils'

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
ensure
  File.unlink(partial) if File.exist?(partial)
end
