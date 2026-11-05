# Keep the signed analyzer's bundled advisory DB readable and cache writes in the job workspace.
require 'fileutils'
root = File.expand_path(ENV.fetch('CI_PROJECT_DIR'))
cache = File.expand_path(ENV.fetch('CS_TRIVY_CACHE_DIR'))
temporary = File.expand_path(ENV.fetch('TMPDIR'))
raise 'Unexpected scanner cache path' unless cache == File.join(root, 'out/trivy-cache')
raise 'Unexpected scanner temporary path' unless temporary == File.join(root, 'out/trivy-tmp')
FileUtils.mkdir_p(temporary)
require 'gcs'
variant = Gcs::Environment.ee? ? 'ee' : 'ce'
source = "/home/gitlab/.cache/trivy/#{variant}"
raise 'Bundled advisory DB is missing' unless File.file?(File.join(source, 'db/metadata.json'))
FileUtils.mkdir_p(cache)
FileUtils.cp_r(File.join(source, '.'), cache)
puts "Bundled #{variant} advisory database copied to the job-owned cache"
