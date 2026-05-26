package com.intp.study.ai.service;

import org.springframework.stereotype.Component;

import java.net.InetAddress;
import java.net.URI;

@Component
public class ProviderUrlGuard {
    public URI requireSafeProviderUri(String rawUrl) {
        URI uri = URI.create(rawUrl);
        String scheme = uri.getScheme();
        if (!"https".equalsIgnoreCase(scheme) && !"http".equalsIgnoreCase(scheme)) {
            throw new IllegalArgumentException("Provider URL scheme is not allowed.");
        }
        String host = uri.getHost();
        if (host == null || host.isBlank()) {
            throw new IllegalArgumentException("Provider URL host is required.");
        }
        if ("http".equalsIgnoreCase(scheme) && !isAllowedLocalProxy(host)) {
            throw new IllegalArgumentException("Provider HTTP URL is only allowed for localhost proxy.");
        }
        if (!isAllowedLocalProxy(host) && isPrivateHost(host)) {
            throw new IllegalArgumentException("Provider URL points to a private or link-local address.");
        }
        return uri;
    }

    private boolean isAllowedLocalProxy(String host) {
        return "localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host) || "::1".equals(host);
    }

    private boolean isPrivateHost(String host) {
        try {
            InetAddress address = InetAddress.getByName(host);
            return address.isAnyLocalAddress()
                    || address.isLoopbackAddress()
                    || address.isLinkLocalAddress()
                    || address.isSiteLocalAddress();
        } catch (Exception ignored) {
            return false;
        }
    }
}
