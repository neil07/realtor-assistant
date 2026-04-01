# HTTP Summary

| kind           | scenario_id             | intent           | action                 | awaiting                          | note                                                   |
| -------------- | ----------------------- | ---------------- | ---------------------- | --------------------------------- | ------------------------------------------------------ |
| live_dialogue  | INIT-E1-A1-01           | listing_video    | start_video            | style_selection                   | Referral entry, direct photo send                      |
| live_dialogue  | INIT-E1-A2-01           | first_contact    | welcome                | -                                 | Referral entry, user asks if this is an app            |
| live_dialogue  | INIT-E1-A3-01           | first_contact    | welcome                | -                                 | Referral entry, user asks about security               |
| live_dialogue  | INIT-E4-A4-01           | daily_insight    | start_daily_insight    | -                                 | Natural traffic, new user asks for daily insight       |
| live_dialogue  | INIT-E4-A1-01           | listing_video    | start_video            | style_selection                   | Natural traffic, new user sends photos with no context |
| live_dialogue  | INIT-E4-A7-01           | first_contact    | welcome                | -                                 | Natural traffic, user asks price before trying         |
| targeted_probe | PROBE-APP-01            | first_contact    | welcome                | -                                 | trust/setup confusion                                  |
| targeted_probe | PROBE-PRICE-01          | first_contact    | welcome                | -                                 | pricing sensitivity                                    |
| targeted_probe | PROBE-TRUST-01          | first_contact    | welcome                | -                                 | security trust question                                |
| targeted_probe | PROBE-FIRSTSTEP-01      | first_contact    | welcome                | -                                 | needs starter task framing                             |
| targeted_probe | PROBE-INSIGHTFIRST-01   | property_content | start_property_content | media_or_missing_property_context | insight-first natural phrasing                         |
| targeted_probe | PROBE-INSIGHT-REFINE-01 | off_topic        | reject                 | -                                 | post-insight refinement                                |
| targeted_probe | PROBE-POST-DELIVERY-01  | style_selection  | set_style              | -                                 | style keyword after delivery                           |
| targeted_probe | PROBE-POST-DELIVERY-02  | style_selection  | set_style              | -                                 | natural revision phrasing after delivery               |
