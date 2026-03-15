import React, { useCallback } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Alert } from 'react-native';
import { Colors } from '../../constants/colors';
import { useConnectionStore } from '../../store/connectionStore';
import * as SecureStore from 'expo-secure-store';

const APP_VERSION = '1.0.0';

export default function SettingsScreen(): React.JSX.Element {
  const { isOnline, tunnelUrl, disconnect } = useConnectionStore();

  const handleDisconnect = useCallback(() => {
    Alert.alert(
      'Disconnect',
      'This will unpair your phone. You will need to scan the QR code again.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Disconnect',
          style: 'destructive',
          onPress: async () => {
            await SecureStore.deleteItemAsync('tunnelUrl');
            await SecureStore.deleteItemAsync('sessionToken');
            disconnect();
          },
        },
      ],
    );
  }, [disconnect]);

  const handleReconnect = useCallback(async () => {
    // Clear stored credentials and redirect to pair screen
    await SecureStore.deleteItemAsync('tunnelUrl');
    await SecureStore.deleteItemAsync('sessionToken');
    disconnect();
  }, [disconnect]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.sectionTitle}>PC Connection</Text>
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.label}>Status</Text>
          <View style={[styles.badge, isOnline ? styles.badgeOnline : styles.badgeOffline]}>
            <Text style={[styles.badgeText, isOnline ? styles.badgeTextOnline : styles.badgeTextOffline]}>
              {isOnline ? 'Connected' : 'Offline'}
            </Text>
          </View>
        </View>

        {tunnelUrl && (
          <View style={styles.row}>
            <Text style={styles.label}>Tunnel</Text>
            <Text style={styles.value} numberOfLines={1}>
              {tunnelUrl.length > 35 ? tunnelUrl.slice(0, 35) + '...' : tunnelUrl}
            </Text>
          </View>
        )}

        <View style={styles.buttonRow}>
          <TouchableOpacity style={styles.reconnectButton} onPress={handleReconnect}>
            <Text style={styles.reconnectText}>Reconnect via QR</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.disconnectButton} onPress={handleDisconnect}>
            <Text style={styles.disconnectText}>Disconnect</Text>
          </TouchableOpacity>
        </View>
      </View>

      <Text style={styles.sectionTitle}>App Info</Text>
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.label}>Version</Text>
          <Text style={styles.value}>{APP_VERSION}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.label}>Build</Text>
          <Text style={styles.value}>1</Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg.primary },
  content: { padding: 16, paddingBottom: 40 },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 12,
    marginTop: 8,
  },
  card: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    marginBottom: 24,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  label: { fontSize: 15, color: Colors.text.secondary },
  value: { fontSize: 15, color: Colors.text.primary, flexShrink: 1 },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12 },
  badgeOnline: { backgroundColor: 'rgba(166,227,161,0.15)' },
  badgeOffline: { backgroundColor: 'rgba(243,139,168,0.15)' },
  badgeText: { fontSize: 13, fontWeight: '600' },
  badgeTextOnline: { color: Colors.status.green },
  badgeTextOffline: { color: Colors.status.danger },
  buttonRow: { flexDirection: 'row', gap: 12, marginTop: 16 },
  reconnectButton: {
    flex: 1,
    padding: 12,
    borderRadius: 10,
    backgroundColor: Colors.accent.blueDark,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.accent.blue,
  },
  reconnectText: { color: Colors.accent.blue, fontSize: 14, fontWeight: '600' },
  disconnectButton: {
    flex: 1,
    padding: 12,
    borderRadius: 10,
    backgroundColor: 'rgba(243,139,168,0.1)',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.status.danger,
  },
  disconnectText: { color: Colors.status.danger, fontSize: 14, fontWeight: '600' },
});
