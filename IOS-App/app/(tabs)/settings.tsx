import React, { useState } from 'react';
import { View, Text, Pressable, ScrollView, Switch, StyleSheet, Alert } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { useRouter } from 'expo-router';
import { Colors } from '../../constants/colors';
import { useConnectionStore } from '../../store/connectionStore';
import StatusBadge from '../../components/StatusBadge';

const APP_VERSION = '1.0.0';
const SECURE_STORE_URL_KEY = 'apollova_tunnel_url';
const SECURE_STORE_TOKEN_KEY = 'apollova_session_token';

export default function SettingsScreen(): React.JSX.Element {
  const router = useRouter();
  const isOnline = useConnectionStore((s) => s.isOnline);
  const tunnelUrl = useConnectionStore((s) => s.tunnelUrl);
  const disconnect = useConnectionStore((s) => s.disconnect);

  const [batchNotifications, setBatchNotifications] = useState(true);
  const [renderNotifications, setRenderNotifications] = useState(true);
  const [errorNotifications, setErrorNotifications] = useState(true);

  const handleDisconnect = (): void => {
    Alert.alert(
      'Disconnect',
      'This will unpair your phone from the PC. You will need to scan the QR code again to reconnect.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Disconnect',
          style: 'destructive',
          onPress: async () => {
            try {
              await SecureStore.deleteItemAsync(SECURE_STORE_URL_KEY);
              await SecureStore.deleteItemAsync(SECURE_STORE_TOKEN_KEY);
            } catch {
              // Best-effort cleanup
            }
            disconnect();
            router.replace('/pair');
          },
        },
      ],
    );
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* Connection Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>PC Connection</Text>

        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Status</Text>
          <StatusBadge status={isOnline ? 'complete' : 'failed'} />
        </View>

        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Server</Text>
          <Text style={styles.infoValue} numberOfLines={1}>
            {tunnelUrl ?? 'Not connected'}
          </Text>
        </View>

        <Pressable style={styles.disconnectButton} onPress={handleDisconnect}>
          <Text style={styles.disconnectText}>Disconnect</Text>
        </Pressable>
      </View>

      {/* Notifications Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Notifications</Text>

        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>Batch Complete</Text>
          <Switch
            value={batchNotifications}
            onValueChange={setBatchNotifications}
            trackColor={{ false: Colors.bg.elevated, true: Colors.accent.blue }}
            thumbColor={Colors.text.primary}
          />
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>Render Complete</Text>
          <Switch
            value={renderNotifications}
            onValueChange={setRenderNotifications}
            trackColor={{ false: Colors.bg.elevated, true: Colors.accent.blue }}
            thumbColor={Colors.text.primary}
          />
        </View>

        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>Error Alerts</Text>
          <Switch
            value={errorNotifications}
            onValueChange={setErrorNotifications}
            trackColor={{ false: Colors.bg.elevated, true: Colors.accent.blue }}
            thumbColor={Colors.text.primary}
          />
        </View>
      </View>

      {/* About Card */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>About</Text>

        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>App Version</Text>
          <Text style={styles.infoValue}>{APP_VERSION}</Text>
        </View>

        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Platform</Text>
          <Text style={styles.infoValue}>iOS</Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  card: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 14,
    padding: 18,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.text.primary,
    marginBottom: 14,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  infoLabel: {
    fontSize: 14,
    color: Colors.text.secondary,
  },
  infoValue: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.primary,
    maxWidth: 200,
    textAlign: 'right',
  },
  disconnectButton: {
    marginTop: 16,
    backgroundColor: Colors.status.danger + '22',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  disconnectText: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.status.danger,
  },
  toggleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  toggleLabel: {
    fontSize: 14,
    color: Colors.text.primary,
  },
});
