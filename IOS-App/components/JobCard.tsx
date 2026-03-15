import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors } from '../constants/colors';
import StatusBadge from './StatusBadge';

interface JobCardProps {
  readonly folder: string;
  readonly songTitle: string;
  readonly template: string;
  readonly status: 'complete' | 'incomplete';
}

export default function JobCard({
  folder,
  songTitle,
  template,
  status,
}: JobCardProps): React.JSX.Element {
  const badgeStatus = status === 'complete' ? 'complete' : 'pending';

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.folderName} numberOfLines={1}>
          {folder}
        </Text>
        <StatusBadge status={badgeStatus} />
      </View>

      <Text style={styles.songTitle} numberOfLines={1}>
        {songTitle}
      </Text>

      <View style={styles.footer}>
        <View style={styles.templateBadge}>
          <Text style={styles.templateText}>{template}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.bg.surface,
    borderRadius: 12,
    padding: 16,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  folderName: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text.secondary,
    flex: 1,
    marginRight: 8,
  },
  songTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: Colors.text.primary,
    marginBottom: 10,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  templateBadge: {
    backgroundColor: Colors.brand.primary,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
  },
  templateText: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.accent.blue,
  },
});
