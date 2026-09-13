package com.kayum.mmc_trading_bot;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Minimal local SOCKS5 forwarder used only by the VPN tunnel. */
final class DirectSocks5Server {
    private static final int PORT = 1080;
    private final QuotexVpnService vpn;
    private final ExecutorService pool = Executors.newCachedThreadPool();
    private volatile boolean running;
    private ServerSocket server;

    DirectSocks5Server(QuotexVpnService vpn) { this.vpn = vpn; }

    void start() throws IOException {
        if (running) return;
        server = new ServerSocket();
        server.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), PORT));
        running = true;
        pool.execute(() -> {
            while (running) {
                try { final Socket s = server.accept(); pool.execute(() -> handle(s)); }
                catch (IOException e) { if (running) break; }
            }
        });
    }

    void stop() {
        running = false;
        try { if (server != null) server.close(); } catch (IOException ignored) {}
        pool.shutdownNow();
    }

    private void handle(Socket client) {
        try (Socket c = client) {
            c.setTcpNoDelay(true);
            DataInputStream in = new DataInputStream(c.getInputStream());
            DataOutputStream out = new DataOutputStream(c.getOutputStream());
            int ver = in.readUnsignedByte();
            int n = in.readUnsignedByte();
            if (ver != 5) return;
            for (int i = 0; i < n; i++) in.readUnsignedByte();
            out.write(new byte[]{5, 0}); out.flush();
            if (in.readUnsignedByte() != 5) return;
            int cmd = in.readUnsignedByte();
            in.readUnsignedByte();
            in.readUnsignedByte();
            int atyp = in.readUnsignedByte();
            String host;
            if (atyp == 1) host = InetAddress.getByAddress(in.readNBytes(4)).getHostAddress();
            else if (atyp == 3) host = new String(in.readNBytes(in.readUnsignedByte()), java.nio.charset.StandardCharsets.US_ASCII);
            else if (atyp == 4) host = InetAddress.getByAddress(in.readNBytes(16)).getHostAddress();
            else return;
            int port = in.readUnsignedShort();
            if (cmd != 1) { sendReply(out, 7, 0, 0); return; }

            Socket upstream = new Socket();
            if (!vpn.protect(upstream)) { upstream.close(); sendReply(out, 1, 0, 0); return; }
            upstream.connect(new InetSocketAddress(host, port), 10000);
            sendReply(out, 0, ((InetSocketAddress) upstream.getLocalSocketAddress()).getAddress(),
                    ((InetSocketAddress) upstream.getLocalSocketAddress()).getPort());
            relay(c, upstream);
        } catch (Exception ignored) { }
    }

    private static void relay(Socket a, Socket b) throws IOException {
        ExecutorService e = Executors.newFixedThreadPool(2);
        e.execute(() -> copy(a, b));
        e.execute(() -> copy(b, a));
        try { e.shutdown(); while (!e.isTerminated()) Thread.sleep(20); }
        catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        finally { try { b.close(); } catch (IOException ignored) {} }
    }

    private static void copy(Socket from, Socket to) {
        try {
            byte[] buf = new byte[16384]; int n;
            while ((n = from.getInputStream().read(buf)) != -1) { to.getOutputStream().write(buf, 0, n); to.getOutputStream().flush(); }
        } catch (IOException ignored) { }
        try { to.shutdownOutput(); } catch (IOException ignored) {}
    }

    private static void sendReply(DataOutputStream out, int code, InetAddress addr, int port) throws IOException {
        byte[] ip = addr == null ? new byte[]{0,0,0,0} : addr.getAddress();
        out.writeByte(5); out.writeByte(code); out.writeByte(0);
        if (ip.length == 16) { out.writeByte(4); out.write(ip); }
        else { out.writeByte(1); out.write(ip, 0, 4); }
        out.writeShort(port); out.flush();
    }
}
