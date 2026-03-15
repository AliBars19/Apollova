import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  Pressable,
  ScrollView,
  StyleSheet,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { Colors } from '../../constants/colors';
import {
  triggerRender,
  tripleRender,
  getRenderStatus,
  RenderStatusResponse,
} from '../../api/endpoints';
import ProgressBar from '../../components/ProgressBar';
import StatusBadge from '../../components/StatusBadge';

type Template = 'Aurora' | 'Mono' | 'Onyx';

const TEMPLATES: readonly Template[] = ['Aurora', 'Mono', 'Onyx'];

export default function RenderScreen(): React.JSX.Element {
  const [selectedTemplate, setSelectedTemplate] = useState<Template>('Aurora');
  const [renderStatus, setRenderStatus] = useState<RenderStatusResponse | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isTripling, setIsTripling] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await getRenderStatus();
      setRenderStatus(status);
    } catch {
      // Handled by connection hook
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchStatus();
    setRefreshing(false);
  }, [fetchStatus]);

  const handleTriggerRender = async (): Promise<void> => {
    setIsTriggering(true);
    try {
      await triggerRender(selectedTemplate);
      Alert.alert('Render Started', `Rendering with ${selectedTemplate} template.`);
      await fetchStatus();
    } catch {
      Alert.alert('Error', 'Failed to trigger render.');
    } finally {
      setIsTriggering(false);
    }
  };

  const handleTripleRender = async (): Promise<void> => {
    Alert.alert(
      'Triple Render',
      `This will render 3 videos using the ${selectedTemplate} template. Continue?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Start',
          onPress: async () => {
            setIsTripling(true);
            try {
              await tripleRender(selectedTemplate);
              Alert.alert('Triple Render Started', `Rendering 3 videos with ${selectedTemplate}.`);
              await fetchStatus();
            } catch {
              Alert.alert('Error', 'Failed to start triple render.');
            } finally {
              setIsTripling(false);
            }
          },
        },
      ],
    );
  };

  const slotEntries = renderStatus?.slots
    ? Object.entries(renderStatus.slots)
    : [];

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={Colors.accent.blue}
        />
      }
    >
      {/* Template Selector */}
      <Text style={styles.sectionTitle}>Template</Text>
      <View style={styles.segmentedControl}>
        {TEMPLATES.map((t) => (
          <Pressable
            key={t}
            style={[styles.segment, selectedTemplate === t && styles.segmentActive]}
            onPress={() => setSelectedTemplate(t)}
          >
            <Text
              style={[styles.segmentText, selectedTemplate === t && styles.segmentTextActive]}
            >
              {t}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Render Actions */}
      <View style={styles.actionsCard}>
        <Pressable
          style={[styles.renderButton, isTriggering && styles.renderButtonDisabled]}
          onPress={handleTriggerRender}
          disabled={isTriggering}
        >
          {isTriggering ? (
            <ActivityIndicator size="small" color={Colors.bg.primary} />
          ) : (
            <Text style={styles.renderButtonText}>Trigger Render</Text>
          )}
        </Pressable>

        <Pressable
          style={[styles.tripleButton, isTripling && styles.renderButtonDisabled]}
          onPress={handleTripleRender}
          disabled={isTripling}
        >
          {isTripling ? (
            <ActivityIndicator size="small" color={Colors.accent.blue} />
          ) : (
            <>
              <Text style={styles.tripleButtonLabel}>3x</Text>
              <Text style={styles.tripleButtonText}>Triple Render</Text>
            </>
          )}
        </Pressable>
      </View>

      {/* Render Status */}
      {renderStatus !== null && (
        <View style={styles.statusCard}>
          <Text style={styles.cardTitle}>Render Status</Text>

          <View style={styles.statusRow}>
            <Text style={styles.statusLabel}>Status</Text>
            <StatusBadge status={renderStatus.isRendering ? 'running' : 'pending'} />
          </View>

          {renderStatus.currentJob !== null && (
            <View style={styles.statusRow}>
              <Text style={styles.statusLabel}>Current Job</Text>
              <Text style={styles.statusValue} numberOfLines={1}>
                {renderStatus.currentJob}
              </Text>
            </View>
          )}

          <View style={styles.progressSection}>
            <Text style={styles.statusLabel}>Progress</Text>
            <ProgressBar percent={renderStatus.progress} height={8} />
            <Text style={styles.progressPercent}>{Math.round(renderStatus.progress)}%</Text>
          </View>

          <View style={styles.statusRow}>
            <Text style={styles.statusLabel}>Render Watcher</Text>
            <StatusBadge status={renderStatus.renderWatcherRunning ? 'running' : 'pending'} />
          </View>
        </View>
      )}

      {/* Account Slots */}
      {slotEntries.length > 0 && (
        <View style={styles.statusCard}>
          <Text style={styles.cardTitle}>Account Slots</Text>
          {slotEntries.map(([account, count]) => (
            <View key={account} style={styles.slotRow}>
              <Text style={styles.slotAccount}>{account}</Text>
              <View style={styles.slotCountBadge}>
                <Text style={styles.slotCountText}>{count}</Text>
              </View>
            </View>
          ))}
        </View>
      )}
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
    paddingBottom: 32,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 10,
    marginTop: 8,
  },
  segmentedControl: {
    flexDirection: 'row',
    backgroundColor: Colors.bg.surface,
    borderRadius: 10,
    padding: 3,
    borderWidth: 1,
    borderColor: Colors.border,
    marginBottom: 20,
  },
  segment: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  segmentActive: {
    backgroundColor: Colors.accent.blue,
  },
  segmentText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.secondary,
  },
  segmentTextActive: {
    color: Colors.bg.primary,
  },
  actionsCard: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 14,
    padding: 18,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    gap: 12,
  },
  renderButton: {
    backgroundColor: Colors.accent.blue,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  renderButtonDisabled: {
    opacity: 0.6,
  },
  renderButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.bg.primary,
  },
  tripleButton: {
    flexDirection: 'row',
    backgroundColor: Colors.bg.elevated,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  tripleButtonLabel: {
    fontSize: 16,
    fontWeight: '800',
    color: Colors.accent.blue,
  },
  tripleButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: Colors.text.primary,
  },
  statusCard: {
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
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  statusLabel: {
    fontSize: 14,
    color: Colors.text.secondary,
  },
  statusValue: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.primary,
    maxWidth: 200,
    textAlign: 'right',
  },
  progressSection: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
    gap: 8,
  },
  progressPercent: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.accent.blue,
  },
  slotRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  slotAccount: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.primary,
  },
  slotCountBadge: {
    backgroundColor: Colors.bg.elevated,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 10,
  },
  slotCountText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.accent.blue,
  },
});
