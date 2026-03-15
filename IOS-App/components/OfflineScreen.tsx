import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { Colors } from '../constants/colors';
import { useConnectionStore } from '../store/connectionStore';
import { getHealth } from '../api/endpoints';

export default function OfflineScreen(): React.JSX.Element {
  const setOnline = useConnectionStore((s) => s.setOnline);

  const handleRetry = async (): Promise<void> => {
    try {
      await getHealth();
      setOnline(true);
    } catch {
      // Stay offline
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.logoText}>APOLLOVA</Text>

        <View style={styles.iconContainer}>
          <Text style={styles.warningIcon}>!</Text>
        </View>

        <Text style={styles.title}>Your PC is offline</Text>
        <Text style={styles.subtitle}>
          Unable to reach your Apollova desktop app. Make sure your PC is turned on and the app is
          running.
        </Text>

        <Pressable style={styles.retryButton} onPress={handleRetry}>
          <Text style={styles.retryText}>Retry Connection</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
    justifyContent: 'center',
    alignItems: 'center',
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 999,
  },
  content: {
    alignItems: 'center',
    paddingHorizontal: 40,
  },
  logoText: {
    fontSize: 28,
    fontWeight: '700',
    color: Colors.text.disabled,
    letterSpacing: 6,
    marginBottom: 48,
    opacity: 0.4,
  },
  iconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: Colors.status.danger,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  warningIcon: {
    fontSize: 32,
    fontWeight: '800',
    color: Colors.bg.primary,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 12,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 15,
    color: Colors.text.secondary,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 36,
  },
  retryButton: {
    backgroundColor: Colors.accent.blue,
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: 12,
  },
  retryText: {
    fontSize: 16,
    fontWeight: '600',
    color: Colors.bg.primary,
  },
});
