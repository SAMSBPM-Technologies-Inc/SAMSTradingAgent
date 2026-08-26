import React from 'react'
import { Text, View } from 'react-native'
import { usePalette } from '../lib/palette'

/**
 * Regulatory notice, rendered at the foot of every screen.
 *
 * Mirrors the web `Layout`'s Disclaimer. Mobile previously carried no copy of
 * it on any screen — it existed only on the web Guide page and inside exported
 * PDFs, in an app that also routes live orders to a broker.
 */

export default function Disclaimer() {
  const C = usePalette()

  return (
    <View style={{
      marginTop: 32,
      paddingTop: 14,
      paddingHorizontal: 16,
      borderTopWidth: 1,
      borderTopColor: C.border,
    }}>
      <Text style={{ fontSize: 10, lineHeight: 15, color: C.fgMuted }}>
        <Text style={{ fontWeight: '700', color: C.fg }}>Not financial advice. </Text>
        SAMSBPM Trading Agent is an automated analysis tool provided for informational
        purposes only. It is not a registered investment adviser, broker-dealer, or
        portfolio manager, and nothing here is a recommendation to buy or sell any
        security. Signals are model output, not research; past signal accuracy does not
        predict future results. Trading involves risk of loss, including total loss of
        capital. You are solely responsible for your investment decisions.
      </Text>
    </View>
  )
}
