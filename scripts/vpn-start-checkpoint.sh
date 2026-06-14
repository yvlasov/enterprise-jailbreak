#!/usr/bin/expect -f

set otp      $env(CHECKPOINT_VPN_OTP)
set password $env(CHECKPOINT_VPN_PASSWORD)
set timeout  120

proc die {msg} {
    puts stderr "ERROR: $msg"
    exit 1
}

spawn snxctl connect

expect {
    "OTP from your Indeed app:" {}
    timeout { die "timed out waiting for OTP prompt" }
    eof     { die "snxctl exited before OTP prompt" }
}
send "$otp\r"

expect {
    "Domain Password:" {}
    timeout { die "timed out waiting for password prompt" }
    eof     { die "snxctl exited before password prompt" }
}
send "$password\r"

expect {
    "Connected since:" {}
    timeout { die "timed out waiting for connection confirmation" }
    eof     { die "snxctl exited without confirming connection" }
}
